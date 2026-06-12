#Description-Provides a feature manager.

# This file is part of Feature Manager, a Fusion add-in that
# provides a feature manager.
#
# Copyright (C) 2020  Thomas Axelsson
#
# This fork elects the MIT license from the original dual-license grant.
# SPDX-License-Identifier: MIT

# Put add-in folder in %appdata%\Autodesk\Autodesk Fusion 360\API\AddIns

# Need to use Visual Studio Code Python extension version 2019.9.34911
# to be able to debug with Fusion.. (2020-07-23)

import adsk.core, adsk.fusion, adsk.cam, traceback

from collections import defaultdict
import json
import os
import shutil
import subprocess
import sys
import threading

NAME = 'Feature Manager'
FILE_DIR = os.path.dirname(os.path.realpath(__file__))
PALETTE_ID = 'featureManager_palette'
COMMAND_ID = 'featureManager_toggle'
HIDE_HORIZONTAL_TIMELINE_COMMAND_ID = 'featureManager_hideHorizontalTimeline'
INITIAL_PALETTE_REFRESH_EVENT = 'featureManager_initialRefresh'
PALETTE_DEFAULT_WIDTH = 435
PALETTE_DEFAULT_HEIGHT = 2000
PALETTE_MIN_WIDTH = 435
PALETTE_MIN_HEIGHT = 300
DOCUMENT_MONITOR_INTERVAL = 1.0
HORIZONTAL_TIMELINE_OVERLAY_HEIGHT = 44
HORIZONTAL_TIMELINE_OVERLAY_BOTTOM_INSET = 0
MAX_AUTO_TIMELINE_ITEMS = 300
LIGHTWEIGHT_TIMELINE_ITEM_TYPES = (
    ('sketch', 'Sketch', 'Fusion/UI/FusionUI/Resources/sketch/Sketch_feature'),
    ('pattern', 'PatternFeature', 'Fusion/UI/FusionUI/Resources/pattern/pattern_rectangular'),
    ('mirror', 'PatternFeature', 'Fusion/UI/FusionUI/Resources/pattern/pattern_mirror'),
    ('plane', 'ConstructionPlane', 'Fusion/UI/FusionUI/Resources/construction/plane_offset'),
    ('axis', 'ConstructionAxis', 'Fusion/UI/FusionUI/Resources/construction/axis_line'),
    ('point', 'ConstructionPoint', 'Fusion/UI/FusionUI/Resources/construction/point'),
    ('component', 'Occurrence', 'Fusion/UI/FusionUI/Resources/Assembly/CreateComponentFromBody'),
    ('copy', 'Occurrence', 'Fusion/UI/FusionUI/Resources/Assembly/CopyPasteInstance'),
    ('joint', 'Joint', 'Fusion/UI/FusionUI/Resources/Assembly/Joint'),
)
LIGHTWEIGHT_DEFAULT_RESOURCE = 'Fusion/UI/FusionUI/Resources/solid/extrude'

# Import relative path to avoid namespace pollution
from . import featuremanagerlib
from .featuremanagerlib import utils
from .featuremanagerlib import events
from .featuremanagerlib import timeline
from .featuremanagerlib import settings
from .featuremanagerlib import manifest
from .featuremanagerlib import error

# Force modules to be fresh during development
import importlib
importlib.reload(featuremanagerlib)
importlib.reload(featuremanagerlib.events)
importlib.reload(featuremanagerlib.timeline)
importlib.reload(featuremanagerlib.settings)
importlib.reload(featuremanagerlib.manifest)
importlib.reload(featuremanagerlib.error)

ui = None
app = None
error_catcher = featuremanagerlib.error.ErrorCatcher(msgbox_in_debug=False)
events_manager = featuremanagerlib.events.EventsManager(error_catcher)
manifest = featuremanagerlib.manifest.read()

html_ready = False
DEBUG_LOGGING = False
TRACE_FUSION_COMMANDS = False
COMMAND_TRACE_IGNORED_IDS = {
    'SelectCommand',
    'CommitCommand',
}
ALLOWED_FEATURE_COMMANDS = {
    'ConstructionPlaneOffsetFromPlaneCommand',
    'CreateSelectionGroupCmd',
    'ConfigureFeatureCmd',
    'ConvertToDMFeatureCommand',
    'Extrude',
    'FindInBrowser',
    'FindInWindow',
    'FusionDeleteCommand',
    'LookAtCommand',
    'ProfileSketchActivate',
    'SelectSketchPlaneCommand',
    'SketchExportToDXFCommand',
    'SketchRedefineCommand',
    'SliceSketchCommand',
}

timeline_item_count = 0
timeline_marker_position = -1
timeline_overlay_process = None
overlay_polling = False
overlay_poll_scheduled = False
palette_refresh_requested = False
document_transitioning = False
document_monitor_scheduled = False
active_document_key = None
overlay_filter_state = {
    'search': '',
    'filters': [],
}
overlay_timeline_state = {
    'markerPosition': -1,
    'timelineCount': -1,
    'suppressedCount': 0,
    'selectedPosition': -1,
}

settings = featuremanagerlib.settings.SettingsManager(
    {
        'enabled': True,
        'horizontalTimelineHidden': False,
    }
)

def debug_log(message):
    if DEBUG_LOGGING:
        print(f'{NAME}: {message}')

def trace_command_event(prefix, event_args):
    if not TRACE_FUSION_COMMANDS:
        return

    command_id = getattr(event_args, 'commandId', '')
    if command_id in COMMAND_TRACE_IGNORED_IDS:
        return

    command_definition = getattr(event_args, 'commandDefinition', None)
    command_name = ''
    resource_folder = ''
    if command_definition:
        try:
            command_name = command_definition.name or ''
        except Exception:
            command_name = ''
        try:
            resource_folder = command_definition.resourceFolder or ''
        except Exception:
            resource_folder = ''
    if resource_folder:
        resource_folder = resource_folder.replace(featuremanagerlib.utils.get_fusion_deploy_folder() + '/', '')

    print(f'{NAME} Command Trace: {prefix} id="{command_id}" name="{command_name}" resource="{resource_folder}"')

def get_active_workspace_id():
    try:
        active_workspace = ui.activeWorkspace
        return active_workspace.id if active_workspace else ''
    except RuntimeError as err:
        # Fusion can temporarily have no readable active workspace during
        # document/environment transitions.
        debug_log(f'activeWorkspace unavailable: {err}')
        return ''

def get_active_document_key():
    try:
        document = app.activeDocument
    except Exception:
        return ''

    if not document:
        return ''

    try:
        name = document.name or ''
    except Exception:
        name = ''

    data_file_id = ''
    try:
        data_file = document.dataFile
        if data_file:
            data_file_id = data_file.id or ''
    except Exception:
        data_file_id = ''

    return f'{name}|{data_file_id}'

def get_enabled():
    return settings.settings.get('enabled', False)

def set_enabled(value):
    settings['enabled'] = value

def get_horizontal_timeline_hidden():
    return settings.settings.get('horizontalTimelineHidden', False)

def set_horizontal_timeline_hidden(value):
    settings['horizontalTimelineHidden'] = value

def get_overlay_actions_dir():
    return os.path.join(FILE_DIR, 'overlay-actions')

def get_overlay_state_path():
    return os.path.join(FILE_DIR, 'overlay_state.json')

# Occurrence types
OCCURRENCE_UNKNOWN_COMP = 0
OCCURRENCE_NEW_COMP = 1
OCCURRENCE_COPY_COMP = 2
OCCURRENCE_SHEET_METAL = 3
OCCURRENCE_BODIES_COMP = 4

TIMELINE_STATUS_OK = 0
TIMELINE_STATUS_PRODUCT_NOT_READY = 1
TIMELINE_STATUS_NOT_PARAMETRIC = 2

OCCURRENCE_RESOURCE_MAP = {
    OCCURRENCE_NEW_COMP: ('Fusion/UI/FusionUI/Resources/Modeling/BooleanNewComponent', ''),
    OCCURRENCE_COPY_COMP: ('Fusion/UI/FusionUI/Resources/Assembly/CopyPasteInstance', ''),
    OCCURRENCE_SHEET_METAL: ('Neutron/UI/Base/Resources/Browser/ComponentSheetMetal', ''),
    #'FusionCreateComponentFromBodyEditCommand' seems to actually create a new component
    OCCURRENCE_BODIES_COMP: ('Fusion/UI/FusionUI/Resources/Assembly/CreateComponentFromBody', ''),
    OCCURRENCE_UNKNOWN_COMP: ('Fusion/UI/FusionUI/Resources/finish/finishX', '')
}

PLANE_RESOURCE_MAP = {
    'ConstructionPlaneOffsetDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_offset', 'FusionDcEditWorkPlaneByPlaneOffsetCommand'),
    'ConstructionPlaneAtAngleDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_angle', 'FusionDcEditWorkPlaneByLineAndAngleCommand'),
    'ConstructionPlaneTangentDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_tangent', 'FusionDcEditWorkPlaneTangentToCylinderCommand'),
    'ConstructionPlaneMidplaneDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_midplane', 'FusionDcEditWorkPlaneFromTwoPlanesCommand'),
    'ConstructionPlaneTwoEdgesDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_two_axis', 'FusionDcEditWorkPlaneFromTwoLinesCommand'),
    'ConstructionPlaneThreePointsDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_three_points', 'FusionDcEditWorkPlaneFromThreePointsCommand'),
    'ConstructionPlaneTangentAtPointDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_point_face', 'FusionDcEditWorkPlaneTangentToFaceAtPointCommand'),
    'ConstructionPlaneDistanceOnPathDefinition': ('Fusion/UI/FusionUI/Resources/construction/plane_onpath', 'FusionDcEditWorkPlaneAlongPathCommand'),
}

FEATURE_RESOURCE_MAP = {
    # This list is hand-crafted. Please respect the work put into this list and
    # retain the Copyright and License stanzas if you copy it.
    # Helpful tools: trace_feature_image function, ImageSorter, Process Monitor.
    # Resources are found in %localappdata%\Autodesk\webdeploy\production\*\
    'Sketch': ('Fusion/UI/FusionUI/Resources/sketch/Sketch_feature', 'SketchActivate'),
    'FormFeature': ('Fusion/UI/FusionUI/Resources/TSpline/TSplineBaseFeatureCreation', 'TSplineBaseFeatureActivate'),
    'LoftFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/loft', 'FusionLoftEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/loft', 'FusionSurfaceLoftEditCommand'),
    'ExtrudeFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/extrude', 'FusionExtrudeEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/extrude', 'FusionSurfaceExtrudeEditCommand'),
    'Occurrence': lambda i: OCCURRENCE_RESOURCE_MAP[featuremanagerlib.timeline.get_occurrence_type(i)],
    'BoundaryFillFeature': ('Fusion/UI/FusionUI/Resources/surface/surface_sculpt', 'FusionSculptEditCommand'),
    'SurfaceDeleteFaceFeature': ('Fusion/UI/FusionUI/Resources/modify/surface_delete', 'FusionDcSurfaceDeleteFaceEditCommand'),
    'RevolveFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/revolve', 'FusionRevolveEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/revolve', 'FusionSurfaceRevolveEditCommand'),
    'SweepFeature': lambda i: ('Fusion/UI/FusionUI/Resources/solid/sweep', 'FusionSweepEditCommand') if i.entity.isSolid else ('Fusion/UI/FusionUI/Resources/surface/sweep', 'FusionSurfaceSweepEditCommand'),
    'RibFeature': ('Fusion/UI/FusionUI/Resources/solid/rib', 'FusionDcRibEditCommand'),
    'WebFeature': ('Fusion/UI/FusionUI/Resources/solid/web', 'FusionDcWebEditCommand'),
    'FeatureManagerFeature': ('Vertical/Timeline', 'FeatureMap'),
    'BoxFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_box', 'BoxPrimitiveEditCommand'),
    'CylinderFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_cylinder', 'CylinderPrimitiveEditCommand'),
    'SphereFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_sphere', 'SpherePrimitiveEditCommand'),
    'TorusFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_torus', 'TorusPrimitiveEditCommand'),
    'CoilFeature': ('Fusion/UI/FusionUI/Resources/solid/Coil', 'CoilPrimitiveEditCommand'),
    'PipeFeature': ('Fusion/UI/FusionUI/Resources/solid/primitive_pipe', 'PipePrimitiveEditCommand'),
    'RectangularPatternFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_rectangular', 'FusionDcRectangularPatternEditCommand'),
    'CircularPatternFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_circular', 'FusionDcCircularPatternEditCommand'),
    'PathPatternFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_path', 'FusionDcPathPatternEditCommand'),
    'MirrorFeature': ('Fusion/UI/FusionUI/Resources/pattern/pattern_mirror', 'FusionDcMirrorPatternEditCommand'),
    'ThickenFeature': ('Fusion/UI/FusionUI/Resources/surface/thicken', 'FusionDcSurfaceThickenEditCommand'),
    'BaseFeature': ('Fusion/UI/FusionUI/Resources/Modeling/BaseFeature', 'BaseFeatureActivate'),
    'MeshPlaneCutFeature': ('Applications/ParaMesh/UI/ParaMeshUI/Resources/Icons/ParaMeshPlaneCut', 'ParaMeshDcPlaneCutEditCommand'),
    'RemoveFeature': ('Fusion/UI/FusionUI/Resources/_return', ''),
    'HoleFeature': ('Fusion/UI/FusionUI/Resources/solid/hole', 'FusionDcHoleEditCommand'),
    'ThreadFeature': ('Fusion/UI/FusionUI/Resources/solid/thread', 'FusionDcThreadEditCommand'),

    # Solid Modify
    'FilletFeature': ('Fusion/UI/FusionUI/Resources/Modeling/FilletEdges', 'FusionDcFilletEditCommand'),
    'ChamferFeature': ('Fusion/UI/FusionUI/Resources/Modeling/Chamfer', 'FusionDcChamferEditCommand'),
    'ShellFeature': ('Fusion/UI/FusionUI/Resources/Modeling/ShellBody', 'FusionDcShellFeatureEditCommand'),
    'DraftFeature': ('Fusion/UI/FusionUI/Resources/solid/draft', 'FusionDcDraftEditCommand'),
    'ScaleFeature': ('Fusion/UI/FusionUI/Resources/modify/scale', 'FusionDcScaleEditCommand'),
    'CombineFeature': ('Fusion/UI/FusionUI/Resources/modify/combine', 'FusionCombineEditCommand'),
    'ReplaceFaceFeature': ('Fusion/UI/FusionUI/Resources/modify/replace_face', 'FusionDcReplaceFaceEditCommand'),
    'SplitFaceFeature': ('Fusion/UI/FusionUI/Resources/modify/split_face', 'FusionDcSplitFaceEditCommand'),
    'SplitBodyFeature': ('Fusion/UI/FusionUI/Resources/modify/split', 'FusionDcSplitBodyEditCommand'),

    # Surface Create only
    'OffsetFacesFeature': ('Fusion/UI/FusionUI/Resources/Modeling/OffsetFaces', 'FusionOffsetFacesEditCommand'),
    'PatchFeature': ('Fusion/UI/FusionUI/Resources/surface/patch', 'FusionSurfacePatchEditCommand'),
    'RuledSurfaceFeature': ('Fusion/UI/FusionUI/Resources/surface/ruled', 'FusionDcSurfaceRuledEditCommand'),
    'OffsetFeature': ('Fusion/UI/FusionUI/Resources/surface/offset', 'FusionDcSurfaceOffsetEditCommand'),

    # Surface Modify only
    'TrimFeature': ('Fusion/UI/FusionUI/Resources/surface/trim', 'FusionDcSurfaceTrimEditCommand'),
    'ExtendFeature': ('Fusion/UI/FusionUI/Resources/surface/extend', 'FusionDcSurfaceExtendEditCommand'),
    'StitchFeature': ('Fusion/UI/FusionUI/Resources/surface/stitch', 'FusionSurfaceStitchEditCommand'),
    'UnstitchFeature': ('Fusion/UI/FusionUI/Resources/surface/unstitch', 'FusionSurfaceUnStitchEditCommand'),
    'ReverseNormalFeature': ('Fusion/UI/FusionUI/Resources/modify/surface_reverse_normal', 'FusionDcReverseNormalEdit'),

    # Assembly
    'Joint': ('Fusion/UI/FusionUI/Resources/Assembly/joint', 'DcEditJointAssembleCmd'),
    'AsBuiltJoint': ('Fusion/UI/FusionUI/Resources/Assembly/JointAsBuilt', 'DcEditJointAsBuiltCmd'),
    'JointOrigin': ('Fusion/UI/FusionUI/Resources/construction/jointorigin', 'EditJointOriginR2Cmd'),
    'RigidGroup': ('Fusion/UI/FusionUI/Resources/Assembly/RigidGroup', 'DcEditRigidGroupCmd'),
    'Snapshot': ('Fusion/UI/FusionUI/Resources/Assembly/Snapshot', 'SnapshotActivate'),

    # Planes
    'ConstructionPlane': lambda i: PLANE_RESOURCE_MAP.get(featuremanagerlib.utils.short_class(i.entity.definition)),
    
    # Not allowed to access entity for these (API mismatch?)
    # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921
    # Move: FusionDcMoveCopyEditCommand
    # Align: FusionDcAlignEditCommand
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/Flange',
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/Bend',
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/ConvertToSheetMetal',
    # '2 : InternalValidationError : res': 'Fusion/UI/FusionSheetMetalUI/Resources/FlatPattern',
    # insert derive feature: 'Fusion/UI/FusionUI/Resources/Derive/CloneWM',
}

GENERIC_FEATURE_RESOURCE_BY_NAME = [
    (('lavorazione mesh di base', 'base mesh feature'), ('Fusion/UI/FusionUI/Resources/TSpline/Convert/MeshBody', 'MeshBaseFeatureActivate')),
    (('modifica', 'edit'), ('Applications/ParaMesh/UI/ParaMeshUI/Resources/Icons/ParaMeshMove', 'ParaMeshDcMoveCopyEditCommand')),
    (('sezionemesh', 'mesh section'), ('Applications/ParaMesh/UI/ParaMeshUI/Resources/Icons/ParaMeshPlanarSection', 'ParaMeshDcPlanarSectionEditCommand')),
    (('scala', 'scale'), ('Applications/ParaMesh/UI/ParaMeshUI/Resources/Icons/ParaMeshScale', 'ParaMeshDcScaleEditCommand')),
    (('corpo->comp', 'body->comp', 'body to component'), ('Fusion/UI/FusionUI/Resources/Assembly/CreateComponentFromBody', '')),
]

def get_feature_image(obj, entity=None):
    match = get_feature_res(obj, entity)

    if not match or not match[0]:
        # Image not mapped
        image = 'Fusion/UI/FusionUI/Resources/finish/finishX'
    else:
        image = match[0]
    
    return get_image_path(image)

def get_feature_edit_command_id(obj):
    match = get_feature_res(obj)

    if not match or not match[1]:
        return None
    else:
        return match[1]

def get_feature_res(obj, entity=None):
    if entity is None:
        entity = get_timeline_entity(obj)
    if entity is None:
        return None
    fusionType = featuremanagerlib.utils.short_class(entity)
    match = FEATURE_RESOURCE_MAP.get(fusionType)
    if not match and fusionType == 'Feature':
        name = (obj.name or '').strip().lower()
        for prefixes, resource in GENERIC_FEATURE_RESOURCE_BY_NAME:
            if any(name.startswith(prefix) for prefix in prefixes):
                match = resource
                break
    if callable(match):
        try:
            match = match(obj)
        except RuntimeError:
            match = None
    return match

def get_image_path(subpath):
    path = f'{featuremanagerlib.utils.get_fusion_deploy_folder()}/{subpath}/16x16.png'
    if os.path.exists(path):
        return path
    else:
        print(f'File does not exist: {path}')
        return None

def get_fusion_resource_file(subpath):
    path = f'{featuremanagerlib.utils.get_fusion_deploy_folder()}/{subpath}'
    if os.path.exists(path):
        return path
    else:
        print(f'File does not exist: {path}')
        return None

def get_optional_image_path(subpath):
    path = f'{featuremanagerlib.utils.get_fusion_deploy_folder()}/{subpath}/16x16.png'
    return path if os.path.exists(path) else None

def get_menu_icon_paths():
    icon_resources = {
        'configure': 'Fusion/UI/FusionUI/Resources/Modeling/DesignConfiguration',
        'convert-dm': 'Fusion/UI/FusionUI/Resources/surface/extend',
        'create-group': 'Fusion/UI/FusionUI/Resources/Timeline/GroupFeature',
        'create-selection-set': 'Neutron/UI/Components/Resources/Icons/CreateSelectionSet',
        'delete': 'Fusion/UI/FusionUI/Resources/modify/delete',
        'edit-profile-sketch': 'Fusion/UI/FusionUI/Resources/sketch/sketch_activate',
        'edit-sketch': 'Fusion/UI/FusionUI/Resources/sketch/sketch_activate',
        'export-dxf': 'Fusion/UI/FusionUI/Resources/File/ExportDXF',
        'extrude': 'Fusion/UI/FusionUI/Resources/solid/extrude',
        'find-browser': 'Neutron/UI/Components/Resources/Icons/EntityFinder',
        'find-window': 'Neutron/UI/Commands/Resources/Camera/ZoomWindow',
        'look-at': 'Neutron/UI/Commands/Resources/Camera/LookAt',
        'offset-plane': 'Fusion/UI/FusionUI/Resources/construction/plane_offset',
        'redefine-sketch-plane': 'Fusion/UI/FusionUI/Resources/sketch/sketch_create',
        'roll-marker': 'Fusion/UI/FusionUI/Resources/Timeline/RollBack',
        'slice-sketch': 'Fusion/UI/FusionUI/Resources/sketch/slice',
        'ungroup': 'Fusion/UI/FusionUI/Resources/Timeline/GroupFeature',
    }
    return {
        name: get_optional_image_path(resource)
        for name, resource in icon_resources.items()
    }

def find_commands(substring):
    return [c.id for c in ui.commandDefinitions if substring in c.id.lower()]

def find_commands_by_resource_folder(folder):
    commands = []
    for c in ui.commandDefinitions:
        try:
            if folder in c.resourceFolder.lower():
                commands.append(c.id)
        except:
            pass
    return commands

# ui.commandDefinitions.itemById('').resourceFolder
# design.rootComponent.allOccurrences[0].component.sketches

def invalidate(send=True, clear=False, force=False):
    global timeline_item_count
    global timeline_marker_position
    global html_ready
    global document_transitioning

    if document_transitioning and not clear:
        if get_active_workspace_id() == 'FusionSolidEnvironment':
            document_transitioning = False
        else:
            return

    palette = ui.palettes.itemById(PALETTE_ID)

    if not palette or (not html_ready and not force):
        return

    debug_log(f'invalidate send={send} clear={clear} force={force}')

    message = ""
    features = []
    lightweight_mode = False
    max_parents = 0
    visual_timeline_item_count = timeline_item_count
    visual_marker_position = timeline_marker_position
    if not clear:
        timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
        if timeline_status == TIMELINE_STATUS_OK:
            design = adsk.fusion.Design.cast(app.activeProduct)
            if is_stale_timeline_for_empty_design(timeline, design):
                timeline_item_count = -1
                timeline_marker_position = -1
                visual_timeline_item_count = -1
                visual_marker_position = -1
            else:
                timeline_item_count = timeline.count
                timeline_marker_position = timeline.markerPosition
                visual_timeline_item_count = get_visual_marker_position(timeline, timeline.count)
                visual_marker_position = get_visual_marker_position(timeline, timeline_marker_position)
                if timeline.count > MAX_AUTO_TIMELINE_ITEMS:
                    features, max_parents = get_lightweight_features(timeline)
                    lightweight_mode = True
                else:
                    features, max_parents = get_features(timeline)
        elif timeline_status == TIMELINE_STATUS_PRODUCT_NOT_READY:
            timeline_item_count = -1
            timeline_marker_position = -1
            visual_timeline_item_count = -1
            visual_marker_position = -1
        elif timeline_status == TIMELINE_STATUS_NOT_PARAMETRIC:
            timeline_item_count = -1
            timeline_marker_position = -1
            visual_timeline_item_count = -1
            visual_marker_position = -1
            message = "Design is not parametric"
        else:
            print("Unhandled timeline status:", timeline_status)

    action = 'setTimeline'
    data = {
         'features': features,
         'max-parents': max_parents,
         'menu-icons': get_menu_icon_paths(),
         'message': message,
         'marker-position': visual_marker_position,
         'timeline-count': visual_timeline_item_count,
         'suppressed-count': count_suppressed_features(features),
         'feature-filters': overlay_filter_state,
         'lightweight-mode': lightweight_mode,
    }
    write_overlay_state(data)

    if not send:
        # Cannot do sendInfoToHTML inside the HTML event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        html_command = {'action': 'setTimeline', 'data': data}
        return html_command
    else:
        debug_log(f'sending timeline update features={len(features)} message="{message}"')
        palette.sendInfoToHTML('setTimeline', json.dumps(data))

def reset_timeline_state():
    global timeline_item_count
    global timeline_marker_position
    global timeline_cache_tree
    global timeline_cache_map

    timeline_item_count = -1
    timeline_marker_position = -1
    timeline_cache_tree = None
    timeline_cache_map = None
    clear_overlay_selected_position()

    data = get_empty_timeline_data()
    write_overlay_state(data)
    return data

def clear_palette_timeline():
    data = reset_timeline_state()

    palette = ui.palettes.itemById(PALETTE_ID)
    if not palette:
        return

    try:
        palette.sendInfoToHTML('setTimeline', json.dumps(data))
    except Exception as err:
        debug_log(f'failed to clear palette timeline: {err}')

def get_empty_timeline_data():
    return {
         'features': [],
         'max-parents': 0,
         'menu-icons': {},
         'message': '',
         'marker-position': -1,
         'timeline-count': -1,
         'suppressed-count': 0,
         'feature-filters': overlay_filter_state,
         'lightweight-mode': False,
    }

def get_empty_timeline_command():
    data = get_empty_timeline_data()
    write_overlay_state(data)
    return {'action': 'setTimeline', 'data': data}

def count_suppressed_features(features):
    count = 0
    for feature in features:
        if feature.get('type') != 'GROUP' and feature.get('suppressed'):
            count += 1
        count += count_suppressed_features(feature.get('children', []))
    return count

def write_overlay_state(timeline_data=None):
    global overlay_timeline_state

    if timeline_data is not None:
        timeline_count = timeline_data.get('timeline-count', -1)
        selected_position = timeline_data.get(
            'selected-position',
            overlay_timeline_state.get('selectedPosition', -1))
        if timeline_count < 0 or selected_position > timeline_count:
            selected_position = -1
        overlay_timeline_state = {
            'markerPosition': timeline_data.get('marker-position', -1),
            'timelineCount': timeline_count,
            'suppressedCount': timeline_data.get('suppressed-count', 0),
            'selectedPosition': selected_position,
        }

    state = {
        'markerPosition': overlay_timeline_state.get('markerPosition', -1),
        'timelineCount': overlay_timeline_state.get('timelineCount', -1),
        'suppressedCount': overlay_timeline_state.get('suppressedCount', 0),
        'selectedPosition': overlay_timeline_state.get('selectedPosition', -1),
        'search': overlay_filter_state.get('search', ''),
        'filters': overlay_filter_state.get('filters', []),
    }
    try:
        with open(get_overlay_state_path(), 'w', encoding='utf-8') as f:
            json.dump(state, f)
    except Exception as err:
        debug_log(f'failed to write overlay state: {err}')

def clear_overlay_selected_position():
    overlay_timeline_state['selectedPosition'] = -1
    write_overlay_state()

def set_overlay_selected_position(feature_ids):
    overlay_timeline_state['selectedPosition'] = get_overlay_selected_position(feature_ids)
    write_overlay_state()

def get_overlay_selected_position(feature_ids):
    if not feature_ids or not timeline_cache_map:
        return -1

    try:
        feature_id = int(feature_ids[-1])
    except Exception:
        return -1

    node = timeline_cache_map.get(feature_id)
    if not node or node.marker_position is None:
        return -1

    timeline_count = overlay_timeline_state.get('timelineCount', -1)
    selected_position = node.marker_position + 1
    if timeline_count >= 0:
        selected_position = min(selected_position, timeline_count)
    return max(1, selected_position)

class TimelineObjectNode:
    def __init__(self, obj, id, marker_position=None):
        self.obj = obj
        self.id = id
        self.children = []
        self.marker_position = marker_position
        self.marker_after_position = marker_position + 1 if marker_position is not None else None

timeline_cache_tree = None
timeline_cache_map = None
def get_visual_marker_position(timeline, native_marker_position):
    visual_position = 0
    marker_position = max(0, min(native_marker_position, timeline.count))

    for native_position, obj in enumerate(timeline):
        if native_position >= marker_position:
            break
        if obj.isGroup:
            visual_position += obj.count
        else:
            visual_position += 1

    return visual_position

def get_native_marker_position(timeline, visual_marker_position):
    visual_position = 0
    target_position = max(0, visual_marker_position)

    for native_position, obj in enumerate(timeline):
        item_visual_width = obj.count if obj.isGroup else 1
        if target_position <= visual_position:
            return native_position
        if target_position <= visual_position + item_visual_width:
            return native_position + 1
        visual_position += item_visual_width

    return timeline.count

def get_features(timeline):
    global timeline_cache_tree, timeline_cache_map
    flat_timeline = featuremanagerlib.timeline.flatten_timeline(timeline)
    timeline_cache_tree, timeline_cache_map = build_timeline_tree(flat_timeline)

    component_parent_map = get_component_parent_map()

    return get_features_from_node(timeline_cache_tree, component_parent_map)

def get_lightweight_features(timeline):
    global timeline_cache_tree, timeline_cache_map
    flat_timeline = featuremanagerlib.timeline.flatten_timeline(timeline)
    timeline_cache_tree, timeline_cache_map = build_timeline_tree(flat_timeline)
    return get_lightweight_features_from_node(timeline_cache_tree)

def get_lightweight_features_from_node(timeline_tree_node):
    features = []
    max_parents = 0
    for child_node in timeline_tree_node.children:
        obj = child_node.obj
        feature = {
            'id': str(child_node.id),
            'name': obj.name,
            'suppressed': obj.isSuppressed,
            'rolledBack': obj.isRolledBack,
            'marker-position': child_node.marker_position,
            'marker-after-position': child_node.marker_after_position,
            'lightweight': True,
        }
        feature.update(get_timeline_object_health(obj))

        if child_node.children:
            feature['type'] = 'GROUP'
            feature['image'] = get_fusion_resource_file('Neutron/UI/Base/Resources/Folder/folder.png')
            feature['expanded-image'] = get_fusion_resource_file('Neutron/UI/Base/Resources/Palette/TipsAndTricks/10x10-ArrowDown@2x.png')
            feature['collapsed-image'] = get_fusion_resource_file('Neutron/UI/Base/Resources/Palette/TipsAndTricks/10x10-ArrowRight@2x.png')
            feature['collapsed'] = obj.isCollapsed
            feature['children'], group_max_parents = get_lightweight_features_from_node(child_node)
            if group_max_parents > max_parents:
                max_parents = group_max_parents
        else:
            lightweight_type, image_resource = get_lightweight_feature_type_and_resource(obj.name)
            feature['type'] = lightweight_type
            feature['image'] = get_image_path(image_resource)

        features.append(feature)

    return (features, max_parents)

def get_lightweight_feature_type_and_resource(name):
    normalized_name = (name or '').lower()
    for marker, feature_type, image_resource in LIGHTWEIGHT_TIMELINE_ITEM_TYPES:
        if marker in normalized_name:
            return feature_type, image_resource
    return 'TimelineFeature', LIGHTWEIGHT_DEFAULT_RESOURCE

def get_features_from_node(timeline_tree_node, component_parent_map):
    features = []
    max_parents = 0
    for i, child_node in enumerate(timeline_tree_node.children):
        obj = child_node.obj

        feature = {
            'id': str(child_node.id),
            'name': obj.name,
            'suppressed': obj.isSuppressed,
            'rolledBack': obj.isRolledBack,
            'marker-position': child_node.marker_position,
            'marker-after-position': child_node.marker_after_position,
            }
        feature.update(get_timeline_object_health(obj))

        # Might there be empty groups?
        if child_node.children:
            # Group
            feature['type'] = 'GROUP'
            feature['image'] = get_fusion_resource_file('Neutron/UI/Base/Resources/Folder/folder.png')
            feature['expanded-image'] = get_fusion_resource_file('Neutron/UI/Base/Resources/Palette/TipsAndTricks/10x10-ArrowDown@2x.png')
            feature['collapsed-image'] = get_fusion_resource_file('Neutron/UI/Base/Resources/Palette/TipsAndTricks/10x10-ArrowRight@2x.png')
            feature['collapsed'] = obj.isCollapsed
            feature['children'], group_max_parents = get_features_from_node(child_node,
                                                                            component_parent_map)
            if group_max_parents > max_parents:
                max_parents = group_max_parents
        else:
            # Not group
            entity = get_timeline_entity(obj)
            
            if entity:
                feature['type'] = featuremanagerlib.utils.short_class(entity)
                feature['image'] = get_feature_image(obj, entity)
                parents = get_feature_parent_path(component_parent_map,
                                                  obj,
                                                  entity)
                feature['parent-components'] = parents
                if len(parents) > max_parents:
                    max_parents = len(parents)
            else:
                # Move and Align and more does not allow us to access their entity attribute
                # Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-cannot-access-entity-of-quot-move-quot-feature/m-p/9651921

                if obj.name.startswith('Derived from '):
                    feature['type'] = 'InsertDerive'
                    feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/Derive/CloneWM')
                else:
                    feature['type'] = '? (Feature info access prohibited by Fusion 360)'
                    feature['image'] = get_image_path('Fusion/UI/FusionUI/Resources/TSpline/Error')

            if feature['type'] == 'Occurrence':
                # Fusion uses a space separator for the timeline object name, but sometimes the first part is empty.
                # Strip the whitespace to make the list cleaner.
                feature['name'] = feature['name'].lstrip()
                if featuremanagerlib.timeline.get_occurrence_type(obj) != OCCURRENCE_BODIES_COMP:
                    # Name is a read-only instance variant of the component's name,
                    # with a prefix on it.
                    # Let the user modify the component's name instead
                    feature['edit-name'] = entity.component.name

        features.append(feature)

    return (features, max_parents)

def get_timeline_object_health(obj):
    try:
        health_state = obj.healthState
    except Exception:
        return {}

    health = {}
    if health_state == adsk.fusion.FeatureHealthStates.WarningFeatureHealthState:
        health['health-state'] = 'warning'
    elif health_state == adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
        health['health-state'] = 'error'
    else:
        return health

    try:
        health['health-message'] = obj.errorOrWarningMessage or ''
    except Exception:
        health['health-message'] = ''
    return health

def get_feature_parent_path(component_parent_map, obj, feature=None):
    design = app.activeProduct

    if feature is None:
        feature = get_timeline_entity(obj)
    if feature is None:
        return []
    feature_type = featuremanagerlib.utils.short_class(feature)
    if feature_type == 'Occurrence':
        if obj.isRolledBack or obj.isSuppressed:
            # No parent component will be available
            return []
        parent_name = component_parent_map.get(feature.component.name)
        if parent_name is None:
            debug_log('missing parent map entry for occurrence component: ' + feature.component.name)
            return []
    elif feature_type == 'ConstructionPlane':
        if (feature.parent.classType() == 'adsk::fusion::Component' and
            feature.parent != design.rootComponent):
            parent_name = feature.parent.name
        else:
            return []
    elif not hasattr(feature, 'parentComponent'):
        if feature_type not in [ 'Snapshot' ]:
            print("Feature Manager: Unhandled missing parent for " + feature.classType())
        return []
    elif feature.parentComponent == design.rootComponent:
        return []
    else:
        parent_name = feature.parentComponent.name

    path = []
    while parent_name:
        path.append(parent_name)
        # If the parent component was suppressed or rolled back,
        # we won't find it, so stop in that case (get() will return None).
        parent_name = component_parent_map.get(parent_name)
    
    path.reverse()
    return path
    
    

def build_timeline_tree(flat_timeline):
    # The timeline tree returned from Fusion depends on the view state of
    # the GUI timeline control. Objects are grouped/nested only if a group
    # is collapsed in the GUI. Flatten the timeline to always get the same
    # result.

    next_id = 0
    def next_node_id():
        nonlocal next_id
        node_id = next_id
        next_id += 1
        return node_id

    def new_node(obj, marker_position=None):
        node_id = next_node_id()
        node = TimelineObjectNode(obj, node_id, marker_position)
        id_map[node_id] = node
        return node

    id_map = {}
    top_node = new_node(None)
    in_node = top_node
    group_nodes = [top_node]

    def get_group_node(group_obj):
        for group_node in group_nodes:
            if group_node.obj == group_obj:
                return group_node
        group_node = new_node(group_obj)
        group_nodes.append(group_node)
        parent_node = get_group_node(group_obj.parentGroup)
        parent_node.children.append(group_node)
        return group_node
    
    for marker_position, obj in enumerate(flat_timeline):
        node = new_node(obj, marker_position)
        parent_obj = obj.parentGroup
        if parent_obj != in_node.obj:
            in_node = get_group_node(parent_obj)
        in_node.children.append(node)

    set_group_marker_positions(top_node)
    return top_node, id_map

def set_group_marker_positions(node):
    for child in node.children:
        set_group_marker_positions(child)

    if not node.children:
        return

    child_marker_positions = [
        child.marker_position for child in node.children
        if child.marker_position is not None
    ]
    child_marker_after_positions = [
        child.marker_after_position for child in node.children
        if child.marker_after_position is not None
    ]
    if child_marker_positions:
        node.marker_position = min(child_marker_positions)
    if child_marker_after_positions:
        node.marker_after_position = max(child_marker_after_positions)

def get_component_parent_map():
    design = app.activeProduct
    component_parent_map = {}
    parent_map_occurrence(component_parent_map,
     None,
     design.rootComponent.occurrences)

    return component_parent_map

def is_stale_timeline_for_empty_design(timeline, design):
    if not timeline or timeline.count == 0 or not design:
        return False

    try:
        root = design.rootComponent
    except Exception:
        return False

    collection_names = [
        'bRepBodies',
        'meshBodies',
        'sketches',
        'occurrences',
        'constructionPlanes',
        'constructionAxes',
        'constructionPoints',
    ]
    for collection_name in collection_names:
        try:
            collection = getattr(root, collection_name)
            if collection and collection.count > 0:
                return False
        except Exception:
            pass

    debug_log('ignoring nonempty timeline because active design is empty')
    return True

def parent_map_occurrence(component_parent_map, parent_name, occurrences):
    for occurrence in occurrences:
        name = occurrence.component.name
        component_parent_map[name] = parent_name
        parent_map_occurrence(component_parent_map,
         name,
         occurrence.childOccurrences)

def get_view_drop_down():
    qat = ui.toolbars.itemById('QAT')
    file_drop_down = qat.controls.itemById('FileSubMenuCommand')
    view_drop_down = file_drop_down.controls.itemById('ViewWidgetCommand')
    return view_drop_down

def check_timeline():
    global timeline_item_count
    global timeline_marker_position
    global html_ready
    timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
    if timeline_status == TIMELINE_STATUS_OK:
        if (timeline.count != timeline_item_count or
            timeline.markerPosition != timeline_marker_position):
            invalidate()
    else:
        timeline_item_count = -1
        timeline_marker_position = -1

def run(context):
    global ui, app
    debug = False
    with error_catcher:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # Add a command that displays the palette
        toggle_palette_cmd_def = ui.commandDefinitions.itemById(COMMAND_ID)

        if not toggle_palette_cmd_def:
            toggle_palette_cmd_def = ui.commandDefinitions.addButtonDefinition(
                COMMAND_ID,
                'Toggle Feature Manager',
                'Feature Manager\n\n' +
                'A vertical feature manager for Fusion timeline features.',
                './resources/featuremanager')

        events_manager.add_handler(toggle_palette_cmd_def.commandCreated,
                    adsk.core.CommandCreatedEventHandler,
                    toggle_palette_command_created_handler)

        # Add the command to the View menu
        view_drop_down = get_view_drop_down()

        # Recreate this command to clear any stale checkbox definition from
        # earlier experiments.
        timeline_cntrl = view_drop_down.controls.itemById(HIDE_HORIZONTAL_TIMELINE_COMMAND_ID)
        if timeline_cntrl:
            timeline_cntrl.deleteMe()
        hide_horizontal_timeline_cmd_def = ui.commandDefinitions.itemById(
            HIDE_HORIZONTAL_TIMELINE_COMMAND_ID)
        if hide_horizontal_timeline_cmd_def:
            hide_horizontal_timeline_cmd_def.deleteMe()

        hide_horizontal_timeline_cmd_def = ui.commandDefinitions.addButtonDefinition(
            HIDE_HORIZONTAL_TIMELINE_COMMAND_ID,
            'Toggle Horizontal Timeline',
            'Show or hide Fusion\'s native bottom timeline using the Feature Manager bottom bar.')

        events_manager.add_handler(hide_horizontal_timeline_cmd_def.commandCreated,
                    adsk.core.CommandCreatedEventHandler,
                    hide_horizontal_timeline_command_created_handler)
        
        cntrl = view_drop_down.controls.itemById(COMMAND_ID)
        if not cntrl:
            view_drop_down.controls.addCommand(toggle_palette_cmd_def,
                                               'SeparatorAfter_DashboardModeCloseCommand', False) 
        timeline_cntrl = view_drop_down.controls.itemById(HIDE_HORIZONTAL_TIMELINE_COMMAND_ID)
        if not timeline_cntrl:
            view_drop_down.controls.addCommand(hide_horizontal_timeline_cmd_def,
                                               COMMAND_ID, False)
        
        events_manager.add_handler(ui.commandTerminated,
                    adsk.core.ApplicationCommandEventHandler,
                    command_terminated_handler)

        events_manager.add_handler(ui.commandStarting,
                    adsk.core.ApplicationCommandEventHandler,
                    command_starting_handler)

        # Fusion bug: Activated is not called when switching to/from Drawing.
        # https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
        events_manager.add_handler(app.documentActivated,
                    adsk.core.DocumentEventHandler,
                    document_activated_handler)

        events_manager.add_handler(app.documentActivating,
                    adsk.core.DocumentEventHandler,
                    document_activating_handler)

        events_manager.add_handler(app.documentDeactivating,
                    adsk.core.DocumentEventHandler,
                    document_deactivating_handler)

        events_manager.add_handler(app.documentClosing,
                    adsk.core.DocumentEventHandler,
                    document_closing_handler)

        events_manager.add_handler(app.documentClosed,
                    adsk.core.DocumentEventHandler,
                    document_closed_handler)

        events_manager.add_handler(ui.workspacePreDeactivate,
                    adsk.core.WorkspaceEventHandler,
                    workspace_pre_deactivate_handler)

        events_manager.add_handler(ui.workspaceActivated,
                    adsk.core.WorkspaceEventHandler,
                    workspace_activated_handler)

        initial_refresh_event = events_manager.register_event(INITIAL_PALETTE_REFRESH_EVENT)
        events_manager.add_handler(initial_refresh_event,
                    adsk.core.CustomEventHandler,
                    initial_palette_refresh_handler)

        debug_log("Running")

        # Show palette when user starts the add-in manually
        if get_enabled() and app.isStartupComplete:
            show_palette()
            schedule_document_monitor()
        if get_horizontal_timeline_hidden() and app.isStartupComplete:
            start_horizontal_timeline_overlay()
        adsk.autoTerminate(False)

def stop(context):
    with error_catcher:
        debug_log('Stopping')

        events_manager.clean_up()

        # Delete the palette created by this add-in.
        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()
        stop_horizontal_timeline_overlay()

        # Delete controls and associated command definitions created by this add-ins
        view_drop_down = get_view_drop_down()
        cntrl = view_drop_down.controls.itemById(COMMAND_ID)
        if cntrl:
            cntrl.deleteMe()
        cmdDef = ui.commandDefinitions.itemById(COMMAND_ID)
        if cmdDef:
            cmdDef.deleteMe()
        timeline_cntrl = view_drop_down.controls.itemById(HIDE_HORIZONTAL_TIMELINE_COMMAND_ID)
        if timeline_cntrl:
            timeline_cntrl.deleteMe()
        timeline_cmd_def = ui.commandDefinitions.itemById(HIDE_HORIZONTAL_TIMELINE_COMMAND_ID)
        if timeline_cmd_def:
            timeline_cmd_def.deleteMe()
        adsk.terminate()

def toggle_palette_command_execute_handler(args):
    enable = not get_enabled()
    set_enabled(enable)
    debug_log(f'toggle palette enable={enable}')
    if enable:
        if get_active_workspace_id() == 'FusionSolidEnvironment':
            show_palette()
        else:
            ui.messageBox('Feature Manager cannot be shown in this workspace. ' +
                        'It will be shown when you open a Design.')
    else:
        hide_palette()

def hide_horizontal_timeline_command_execute_handler(args):
    hidden = not get_horizontal_timeline_hidden()

    if hidden and not is_horizontal_timeline_overlay_supported():
        set_horizontal_timeline_hidden(False)
        ui.messageBox('Toggle Horizontal Timeline is only supported on Windows.')
        return

    set_horizontal_timeline_hidden(hidden)
    debug_log(f'hide horizontal timeline={hidden}')
    if hidden:
        started = start_horizontal_timeline_overlay()
        if not started:
            set_horizontal_timeline_hidden(False)
            ui.messageBox('Failed to start the horizontal timeline overlay.')
    else:
        stop_horizontal_timeline_overlay()

def is_horizontal_timeline_overlay_supported():
    return os.name == 'nt'

def get_powershell_executable():
    program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
    bundled_pwsh = os.path.join(program_files, 'PowerShell', '7', 'pwsh.exe')
    if os.path.exists(bundled_pwsh):
        return bundled_pwsh

    for executable in ('pwsh.exe', 'powershell.exe'):
        found = shutil.which(executable)
        if found:
            return found

    return None

def is_horizontal_timeline_overlay_running():
    return (timeline_overlay_process is not None and
            timeline_overlay_process.poll() is None)

def start_horizontal_timeline_overlay():
    global timeline_overlay_process

    if not is_horizontal_timeline_overlay_supported():
        return False
    if is_horizontal_timeline_overlay_running():
        start_overlay_polling()
        return True

    powershell = get_powershell_executable()
    overlay_script = os.path.join(FILE_DIR, 'timeline_overlay.ps1')
    if not powershell or not os.path.exists(overlay_script):
        print(f'{NAME}: missing overlay dependency powershell="{powershell}" script="{overlay_script}"')
        return False

    args = [
        powershell,
        '-NoProfile',
        '-Sta',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        overlay_script,
        '-OverlayHeight',
        str(HORIZONTAL_TIMELINE_OVERLAY_HEIGHT),
        '-BottomInset',
        str(HORIZONTAL_TIMELINE_OVERLAY_BOTTOM_INSET),
        '-TimelineResourceFolder',
        os.path.join(featuremanagerlib.utils.get_fusion_deploy_folder(),
                     'Fusion', 'UI', 'FusionUI', 'Resources', 'Timeline'),
        '-FusionDeployFolder',
        featuremanagerlib.utils.get_fusion_deploy_folder(),
    ]
    creationflags = 0
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        creationflags = subprocess.CREATE_NO_WINDOW

    timeline_overlay_process = subprocess.Popen(args, creationflags=creationflags)
    write_overlay_state()
    start_overlay_polling()
    return True

def stop_horizontal_timeline_overlay():
    global timeline_overlay_process

    if not timeline_overlay_process:
        return

    if timeline_overlay_process.poll() is None:
        timeline_overlay_process.terminate()
    timeline_overlay_process = None
    stop_overlay_polling()

def start_overlay_polling():
    global overlay_polling

    if overlay_polling:
        return
    overlay_polling = True
    schedule_overlay_poll(0.75)

def stop_overlay_polling():
    global overlay_polling
    global overlay_poll_scheduled

    overlay_polling = False
    overlay_poll_scheduled = False

def schedule_overlay_poll(delay_seconds=0.75):
    global overlay_poll_scheduled

    if not overlay_polling:
        return
    if overlay_poll_scheduled:
        return
    overlay_poll_scheduled = True
    threading.Timer(delay_seconds, app.fireCustomEvent,
                    args=[INITIAL_PALETTE_REFRESH_EVENT]).start()

def process_overlay_actions():
    actions_dir = get_overlay_actions_dir()
    if not os.path.isdir(actions_dir):
        return

    for filename in sorted(os.listdir(actions_dir)):
        if not filename.lower().endswith('.json'):
            continue
        path = os.path.join(actions_dir, filename)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                command = json.load(f)
            os.remove(path)
        except Exception as err:
            debug_log(f'failed to read overlay action "{filename}": {err}')
            continue

        handle_overlay_action(command)

def handle_overlay_action(command):
    action = command.get('action')
    data = command.get('data') or {}
    debug_log(f'overlay action={action}')

    if action == 'timeline.begin':
        run_timeline_transport_action('begin')
    elif action == 'timeline.previous':
        run_timeline_transport_action('previous')
    elif action == 'timeline.play':
        # Fusion's Timeline.play() advances to the end too quickly for this
        # overlay. The overlay owns animated playback by sending timeline.next
        # ticks instead.
        run_timeline_transport_action('next')
    elif action == 'timeline.next':
        run_timeline_transport_action('next')
    elif action == 'timeline.end':
        run_timeline_transport_action('end')
    elif action == 'featureFilters.changed':
        set_overlay_feature_filters(data)

def run_timeline_transport_action(action):
    timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
    if timeline_status != TIMELINE_STATUS_OK:
        return

    try:
        if action == 'begin':
            timeline.moveToBeginning()
        elif action == 'previous':
            timeline.moveToPreviousStep()
        elif action == 'next':
            timeline.movetoNextStep()
        elif action == 'end':
            timeline.moveToEnd()
        else:
            return
    except Exception as err:
        debug_log(f'timeline transport action "{action}" failed: {err}')
        return

    clear_overlay_selected_position()
    schedule_palette_refresh([0.05, 0.25])

def move_visual_marker(delta):
    timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
    if timeline_status != TIMELINE_STATUS_OK:
        return
    current_position = get_visual_marker_position(timeline, timeline.markerPosition)
    set_visual_marker_position(current_position + delta)

def set_visual_marker_position(visual_marker_position):
    timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
    if timeline_status != TIMELINE_STATUS_OK:
        return
    visual_marker_position = max(0, min(int(visual_marker_position),
                                        get_visual_marker_position(timeline, timeline.count)))
    timeline.markerPosition = get_native_marker_position(timeline, visual_marker_position)
    clear_overlay_selected_position()
    schedule_palette_refresh([0.05, 0.25])

def set_overlay_feature_filters(data):
    global overlay_filter_state

    search = str(data.get('search', ''))
    filters = data.get('filters') or []
    if not isinstance(filters, list):
        filters = []
    filters = [str(filter_name) for filter_name in filters]
    overlay_filter_state = {
        'search': search,
        'filters': filters,
    }
    write_overlay_state()

    palette = ui.palettes.itemById(PALETTE_ID)
    if palette:
        palette.sendInfoToHTML('setFeatureFilters', json.dumps(overlay_filter_state))

def show_palette():
    global html_ready

    palette = ui.palettes.itemById(PALETTE_ID)
    if not palette:
        html_ready = False
        debug_log('creating palette')

        palette = ui.palettes.addTransparent(PALETTE_ID, 'FEATURE MANAGER',
                                    'palette.html',
                                    True, False, True, False, PALETTE_DEFAULT_WIDTH, PALETTE_DEFAULT_HEIGHT)
        palette.setMinimumSize(PALETTE_MIN_WIDTH, PALETTE_MIN_HEIGHT)
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateLeft

        events_manager.add_handler(palette.incomingFromHTML,
                                   adsk.core.HTMLEventHandler,
                                   palette_incoming_from_html_handler)

        events_manager.add_handler(palette.closed,
                                   adsk.core.UserInterfaceGeneralEventHandler,
                                   palette_closed_handler)
        schedule_initial_palette_refresh()
    else:
        debug_log('showing existing palette')
        invalidate()
        if not palette.isVisible:
            palette.isVisible = True
    schedule_document_monitor()

def hide_palette():
    palette = ui.palettes.itemById(PALETTE_ID)
    if palette:
        debug_log('hiding palette')
        palette.isVisible = False

def get_associated_component(entity):
    if isinstance(entity, adsk.fusion.Occurrence):
        return entity.sourceComponent
    elif isinstance(entity, adsk.fusion.ConstructionPlane):
        return entity.parent
    elif not hasattr(entity, 'parentComponent'):
        return None
    else:
        return entity.parentComponent

def add_body_selection_fallback(selection, entity, design, associated_component):
    if not hasattr(entity, 'bodies'):
        return

    if associated_component == design.rootComponent:
        for body in entity.bodies:
            selection.add(body)
    else:
        in_occurrences = design.rootComponent.allOccurrencesByComponent(associated_component)
        for body in entity.bodies:
            for occurrence in in_occurrences:
                selection.add(body.createForAssemblyContext(occurrence))

def build_selection(entity, design, use_body_fallback=False):
    selection = adsk.core.ObjectCollection.create()
    associated_component = get_associated_component(entity)

    if use_body_fallback:
        add_body_selection_fallback(selection, entity, design, associated_component)
        return selection

    if associated_component is None:
        selection.add(entity)
        return selection

    if associated_component == design.rootComponent:
        # There are no occurrences of root. Just a single instance: root.
        selection.add(entity)
    else:
        in_occurrences = design.rootComponent.allOccurrencesByComponent(associated_component)
        if hasattr(entity, 'createForAssemblyContext'):
            for occurrence in in_occurrences:
                selection.add(entity.createForAssemblyContext(occurrence))
        else:
            add_body_selection_fallback(selection, entity, design, associated_component)

    return selection

def set_active_selection(selection):
    active_selections = getattr(ui, 'activeSelections', None)
    if active_selections is None:
        return False, 'No active selection context'

    active_selections.all = selection
    return True, None

def clear_active_selection():
    return set_active_selection(adsk.core.ObjectCollection.create())

def select_timeline_entity(entity, design):
    selection = build_selection(entity, design)
    try:
        return set_active_selection(selection)
    except Exception as first_error:
        fallback_selection = build_selection(entity, design, use_body_fallback=True)
        if fallback_selection.count == 0:
            return False, first_error

    try:
        return set_active_selection(fallback_selection)
    except Exception as fallback_error:
        return False, fallback_error

def build_selection_for_timeline_ids(feature_ids, design, use_body_fallback=False):
    selection = adsk.core.ObjectCollection.create()
    skipped = 0
    for feature_id in feature_ids:
        node = timeline_cache_map.get(int(feature_id))
        if not node:
            skipped += 1
            continue
        entity = get_timeline_entity(node.obj)
        if not entity:
            skipped += 1
            continue
        entity_selection = build_selection(entity, design, use_body_fallback=use_body_fallback)
        for i in range(entity_selection.count):
            selection.add(entity_selection.item(i))
    return selection, skipped

def select_timeline_entities(feature_ids, design):
    selection, skipped = build_selection_for_timeline_ids(feature_ids, design)
    if selection.count == 0:
        return False, 'No selectable entities found'
    try:
        return set_active_selection(selection)
    except Exception as first_error:
        fallback_selection, fallback_skipped = build_selection_for_timeline_ids(
            feature_ids, design, use_body_fallback=True)
        if fallback_selection.count == 0:
            return False, first_error

    try:
        return set_active_selection(fallback_selection)
    except Exception as fallback_error:
        return False, fallback_error

def get_timeline_object_index(obj):
    try:
        return obj.index
    except Exception:
        return None

def timeline_object_is_at_reorder_target(obj, before_index, timeline):
    current_index = get_timeline_object_index(obj)
    if current_index is None:
        return False
    if before_index == -1:
        return current_index == timeline.count - 1
    return current_index == before_index or current_index == before_index - 1

def marker_position_is_inside_node_span(node, before_position):
    if node.marker_position is None or node.marker_after_position is None:
        return False
    return node.marker_position <= before_position <= node.marker_after_position

def reorder_timeline_object_to_end(obj, timeline):
    current_index = get_timeline_object_index(obj)
    if current_index is None:
        return False, 'Could not read timeline item index.'
    if current_index >= timeline.count - 1:
        return True, None

    followers = [timeline.item(i) for i in range(current_index + 1, timeline.count)]
    for follower in followers:
        before_index = get_timeline_object_index(obj)
        if before_index is None:
            return False, 'Could not read updated timeline item index.'
        try:
            if not follower.canReorder(before_index):
                return False, f'Fusion cannot move "{follower.name}" before "{obj.name}".'
            if not follower.reorder(before_index):
                return False, f'Fusion did not move "{follower.name}" before "{obj.name}".'
        except Exception as reorder_error:
            return False, str(reorder_error)

    return timeline_object_is_at_reorder_target(obj, timeline.count, timeline), None

def get_timeline_nodes(feature_ids):
    nodes = []
    if timeline_cache_map is None:
        return None, 'Timeline cache is not ready.'

    for feature_id in feature_ids:
        node = timeline_cache_map.get(feature_id)
        if node is None:
            return None, f'Timeline item is no longer available: {feature_id}'
        nodes.append(node)

    return nodes, None

def group_timeline_nodes(feature_ids, timeline):
    nodes, error_message = get_timeline_nodes(feature_ids)
    if error_message:
        return False, error_message
    if len(nodes) < 2:
        return False, 'Select two or more contiguous timeline items to create a group.'
    if any(node.obj.isGroup for node in nodes):
        return False, 'Cannot group an existing group. Ungroup it first.'
    if any(node.obj.parentGroup for node in nodes):
        return False, 'Cannot group items that are already inside a group. Ungroup them first.'

    raw_positions = [node.marker_position for node in nodes]
    if any(position is None for position in raw_positions):
        return False, 'Could not read timeline positions for the selected items.'
    positions = sorted(raw_positions)

    start_position = positions[0]
    end_position = positions[-1]
    expected_positions = list(range(start_position, end_position + 1))
    if positions != expected_positions:
        return False, 'Only contiguous timeline items can be grouped.'

    try:
        new_group = timeline.timelineGroups.add(start_position, end_position)
    except Exception as group_error:
        return False, str(group_error)

    if not new_group:
        return False, 'Fusion did not create a timeline group.'

    return True, None

def ungroup_timeline_nodes(feature_ids):
    nodes, error_message = get_timeline_nodes(feature_ids)
    if error_message:
        return False, error_message

    groups = []
    for node in nodes:
        if node.obj.isGroup and not any(existing == node.obj for existing in groups):
            groups.append(node.obj)

    if not groups:
        return False, 'Select one or more timeline groups to ungroup.'

    for group in groups:
        try:
            if not group.isCollapsed:
                group.isCollapsed = True
            if not group.deleteMe(False):
                return False, f'Fusion did not ungroup "{group.name}".'
        except Exception as ungroup_error:
            return False, str(ungroup_error)

    return True, None

def set_timeline_nodes_suppressed(feature_ids, suppressed):
    nodes, error_message = get_timeline_nodes(feature_ids)
    if error_message:
        return False, error_message

    target_nodes = [node for node in nodes if not node.obj.isGroup]
    if not target_nodes:
        return False, 'Select one or more timeline features.'

    for node in target_nodes:
        try:
            node.obj.isSuppressed = suppressed
        except Exception as suppress_error:
            return False, f'Failed to update "{node.obj.name}": {suppress_error}'

    return True, None

def get_timeline_entity(obj):
    if obj.isGroup:
        return None
    try:
        return obj.entity
    except RuntimeError as err:
        debug_log(f'entity unavailable for timeline object "{obj.name}": {err}')
        return None

def schedule_initial_palette_refresh():
    schedule_palette_refresh([0.5, 1.5, 3.0])

def schedule_palette_refresh(delays):
    global palette_refresh_requested

    palette_refresh_requested = True
    for delay_seconds in delays:
        threading.Timer(delay_seconds, app.fireCustomEvent,
                        args=[INITIAL_PALETTE_REFRESH_EVENT]).start()

def schedule_document_monitor():
    return

def check_active_document_changed():
    global active_document_key
    global document_transitioning

    current_document_key = get_active_document_key()
    if active_document_key is None:
        active_document_key = current_document_key
        return False

    if current_document_key == active_document_key:
        return False

    debug_log(f'active document changed from "{active_document_key}" to "{current_document_key}"')
    active_document_key = current_document_key
    document_transitioning = True
    clear_palette_timeline()
    schedule_palette_refresh([0.5, 1.5, 3.0])
    return True

def initial_palette_refresh_handler(args):
    global html_ready
    global overlay_poll_scheduled
    global palette_refresh_requested
    global document_monitor_scheduled

    overlay_poll_scheduled = False
    document_monitor_scheduled = False
    process_overlay_actions()
    if overlay_polling:
        schedule_overlay_poll(0.75)

    palette = ui.palettes.itemById(PALETTE_ID)
    if not palette:
        return

    should_refresh = palette_refresh_requested or not html_ready
    palette_refresh_requested = False
    html_ready = True
    if should_refresh:
        invalidate(force=True)

def update_feature_by_id(features, feature_id, values):
    for feature in features:
        if feature.get('id') == feature_id:
            feature.update(values)
            return True
        if update_feature_by_id(feature.get('children', []), feature_id, values):
            return True
    return False

# Event handler for the commandCreated event.
def toggle_palette_command_created_handler(args):
    command = args.command
    events_manager.add_handler(command.execute,
                                adsk.core.CommandEventHandler,
                                toggle_palette_command_execute_handler)

def hide_horizontal_timeline_command_created_handler(args):
    command = args.command
    events_manager.add_handler(command.execute,
                                adsk.core.CommandEventHandler,
                                hide_horizontal_timeline_command_execute_handler)

# Event handler for the palette close event.
def palette_closed_handler(args):
    debug_log('palette closed')
    set_enabled(False)

# Event handler for the palette HTML event.                
def palette_incoming_from_html_handler(args):
    global html_ready
    htmlArgs = adsk.core.HTMLEventArgs.cast(args)
    action = htmlArgs.action
    data = json.loads(htmlArgs.data)
    html_commands = []
    debug_log(f'HTML event action={action}')
    if action == 'ready':
        debug_log('HTML ready')
        html_ready = True

        # Cannot do sendInfoToHTML inside the event handler. We either have to use htmlArgs.returnData or
        # spawn a thread (does not seem very safe? Can we call into the event loop instead?).
        timeline_command = invalidate(send=False, force=True)
        html_commands.append(timeline_command or get_empty_timeline_command())
    elif action == 'setFeatureName':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        visible_name = None
        if data['value'] != '':
            entity = get_timeline_entity(obj)
            if (not obj.isGroup
                and entity
                and entity.classType() == 'adsk::fusion::Occurrence'
                and featuremanagerlib.timeline.get_occurrence_type(obj) != OCCURRENCE_BODIES_COMP):
                # Bonus of not doing a Command transaction: Undo history actually says from and to name.
                entity.component.name = data['value']
                # The shown name will have changed. Invalidate.
                #html_commands.append(invalidate(send=False))
            else:
                obj.name = data['value']
            visible_name = obj.name.lstrip()
        html_commands.append(visible_name)
    elif action == 'selectFeature' or action == 'selectFeatures' or action == 'editFeature':
        feature_ids = data.get('ids')
        if feature_ids is None:
            feature_ids = [data['id']]
        if action == 'selectFeature' or action == 'selectFeatures':
            set_overlay_selected_position(feature_ids)
        ret = True

        design: adsk.fusion.Design = app.activeProduct
        if len(feature_ids) > 0 and not timeline_cache_map:
            ret = False
        elif action == 'selectFeatures':
            if len(feature_ids) == 0:
                clear_active_selection()
            else:
                ret, selection_error = select_timeline_entities(feature_ids, design)
                if not ret:
                    # Palette rows such as timeline groups are valid UI selections
                    # but do not map to selectable Fusion entities. Keep the local
                    # row highlight and clear Fusion's active selection silently.
                    clear_active_selection()
                    ret = True
        else:
            node = timeline_cache_map[feature_ids[0]]
            obj = node.obj
            entity = get_timeline_entity(obj)
            if not entity:
                ret = False
            else:
                ret, selection_error = select_timeline_entity(entity, design)
                if not ret:
                    ui.messageBox(f'Failed to select {featuremanagerlib.utils.short_class(entity)}: {selection_error}')
                    ret = False

        if ret and action == 'editFeature':
            node = timeline_cache_map[feature_ids[0]]
            obj = node.obj
            entity = get_timeline_entity(obj)
            if not entity:
                ret = False
            command_id = get_feature_edit_command_id(obj)
            if ret and command_id and ui.commandDefinitions.itemById(command_id):
                #print("T", ui.terminateActiveCommand())
                ui.commandDefinitions.itemById(command_id).execute()
            elif ret:
                ui.messageBox(f'Editing {featuremanagerlib.utils.short_class(entity)} feature is not supported')
                ret = False
        html_commands.append(ret)
    elif action == 'executeFeatureCommand':
        feature_ids = data.get('ids')
        if feature_ids is None:
            feature_ids = [data['id']]
        command_id = data.get('command-id')
        ret = False
        if len(feature_ids) == 0:
            ui.messageBox('No timeline items selected')
        elif command_id not in ALLOWED_FEATURE_COMMANDS:
            ui.messageBox(f'Unsupported context menu command: {command_id}')
        else:
            design: adsk.fusion.Design = app.activeProduct
            ret, selection_error = select_timeline_entities(feature_ids, design)
            if not ret:
                ui.messageBox(f'Failed to select timeline items: {selection_error}')
            else:
                command_definition = ui.commandDefinitions.itemById(command_id)
                if command_definition:
                    command_definition.execute()
                    ret = True
                else:
                    ui.messageBox(f'Fusion command is not available: {command_id}')
                    ret = False
        html_commands.append(ret)
        html_commands.append(invalidate(send=False))
    elif action == 'groupSelectedFeatures':
        feature_ids = data.get('ids', [])
        ret = False
        timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
        if timeline_status == TIMELINE_STATUS_OK:
            ret, group_error = group_timeline_nodes(feature_ids, timeline)
            if ret:
                schedule_palette_refresh([0.15, 0.5])
            else:
                ui.messageBox(f'Failed to group timeline items: {group_error}')
        html_commands.append(ret)
        html_commands.append(invalidate(send=False))
    elif action == 'ungroupSelectedGroups':
        feature_ids = data.get('ids', [])
        ret, ungroup_error = ungroup_timeline_nodes(feature_ids)
        if ret:
            schedule_palette_refresh([0.15, 0.5])
        else:
            ui.messageBox(f'Failed to ungroup timeline group: {ungroup_error}')
        html_commands.append(ret)
        html_commands.append(invalidate(send=False))
    elif action == 'setFeaturesSuppressed':
        feature_ids = data.get('ids', [])
        suppressed = bool(data.get('suppressed'))
        ret, suppress_error = set_timeline_nodes_suppressed(feature_ids, suppressed)
        if ret:
            schedule_palette_refresh([0.15, 0.5])
        else:
            action_label = 'suppress' if suppressed else 'unsuppress'
            ui.messageBox(f'Failed to {action_label} timeline features: {suppress_error}')
        html_commands.append(ret)
        html_commands.append(invalidate(send=False))
    elif action == 'rollToFeature':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        if obj.isGroup and not obj.isCollapsed:
            # Cannot move to collapsed group.
            # Move to the last item of the group.
            obj = obj[-1]
        elif not obj.isGroup and obj.parentGroup and obj.parentGroup.isCollapsed:
            # Cannot move to object inside collapsed group.
            # Move to the group instead.
            obj = obj.parentGroup
        ret = obj.rollTo(False)
        if ret:
            schedule_palette_refresh([0.15, 0.5])
        html_commands.append(ret)
        html_commands.append(invalidate(send=False))
    elif action == 'reorderFeature':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        before_position = int(data['before-position'])
        ret = False
        timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
        if timeline_status == TIMELINE_STATUS_OK:
            if marker_position_is_inside_node_span(node, before_position):
                ret = True
            else:
                if obj.isGroup and not obj.isCollapsed:
                    obj.isCollapsed = True
                if before_position >= timeline.count:
                    ret, reorder_error = reorder_timeline_object_to_end(obj, timeline)
                    if ret:
                        schedule_palette_refresh([0.15, 0.5])
                    elif reorder_error:
                        ui.messageBox(f'Failed to reorder timeline item: {reorder_error}')
                else:
                    before_index = before_position
                    try:
                        if obj.canReorder(before_index):
                            ret = obj.reorder(before_index)
                            if ret:
                                schedule_palette_refresh([0.15, 0.5])
                        else:
                            ui.messageBox('Fusion cannot reorder this timeline item to that position.')
                    except Exception as reorder_error:
                        if ('featureAtIndex' in str(reorder_error)
                            and timeline_object_is_at_reorder_target(obj, before_index, timeline)):
                            ret = True
                            schedule_palette_refresh([0.15, 0.5])
                        else:
                            ui.messageBox(f'Failed to reorder timeline item: {reorder_error}')
        html_commands.append(ret)
        html_commands.append(invalidate(send=False))
    elif action == 'setGroupCollapsed':
        node = timeline_cache_map[data['id']]
        obj = node.obj
        ret = False
        collapsed = bool(data['collapsed'])
        if obj.isGroup:
            obj.isCollapsed = collapsed
            ret = True
        html_commands.append(ret)
        refresh_command = invalidate(send=False)
        if ret and refresh_command:
            update_feature_by_id(refresh_command['data']['features'], str(data['id']), {'collapsed': collapsed})
        html_commands.append(refresh_command)
    elif action == 'setMarkerPosition':
        timeline_status, timeline = featuremanagerlib.timeline.get_timeline()
        ret = False
        marker_position = None
        if timeline_status == TIMELINE_STATUS_OK:
            visual_marker_position = int(data['position'])
            marker_position = get_native_marker_position(timeline, visual_marker_position)
            timeline.markerPosition = marker_position
            ret = True
            schedule_palette_refresh([0.15, 0.5])
        html_commands.append(ret)
        refresh_command = invalidate(send=False)
        if ret and refresh_command:
            refresh_command['data']['marker-position'] = get_visual_marker_position(timeline, marker_position)
        html_commands.append(refresh_command)

    if html_commands:
        htmlArgs.returnData = json.dumps(html_commands)

def command_terminated_handler(args):
    eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)
    trace_command_event('terminated', eventArgs)

    if document_transitioning:
        return

    # As long as we don't update on command create, we only need to listen for command completion
    # Except Undo, which has a "Cancel" termination reason.
    if (eventArgs.terminationReason != adsk.core.CommandTerminationReason.CompletedTerminationReason and
        eventArgs.commandId != 'UndoCommand'):
        return

    # Helper to trace feature images
    #trace_feature_image(eventArgs)

    # Heavy traffic commands
    if eventArgs.commandId in ['SelectCommand', 'CommitCommand']:
        return
    
    invalidate()

def command_starting_handler(args):
    eventArgs = adsk.core.ApplicationCommandEventArgs.cast(args)
    trace_command_event('starting', eventArgs)

def trace_feature_image(command_terminated_event_args):
    ''' Development function to trace feature images '''
    _, timeline = featuremanagerlib.timeline.get_timeline()
    feature = None
    if timeline:
        try:
            feature = featuremanagerlib.utils.short_class(timeline.item(timeline.count-1).entity)
        except Exception as e:
            feature = str(e)
    folder = command_terminated_event_args.commandDefinition.resourceFolder
    if folder:
        folder = folder.replace(featuremanagerlib.utils.get_fusion_deploy_folder() + '/', '')
    print(f"'{feature}': ('{folder}', ''),")

#########################################################################################
# app.product is not ready at workspaceActivated, but documentActivated does not fire
# when switching to/from Drawing. However, in that case, it seems that the product is
# ready when we call featuremanagerlib.timeline.get_timeline (presumably since the panel has to be recreated)
# Bug: https://forums.autodesk.com/t5/fusion-360-api-and-scripts/api-bug-application-documentactivated-event-do-not-raise/m-p/9020750
#
# PLM360OpenAttachmentCommand + MarkDocumentsForOpenCommand could possibly be used as
# another workaround.
#
# Event order:
# DocumentActivating
# OnWorkspaceActivated
# DocumentActivated
# PLM360OpenAttachmentCommand or MarkDocumentsForOpenCommand
#

def workspace_pre_deactivate_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    global document_transitioning

    debug_log('workspace pre-deactivate')
    document_transitioning = True
    reset_timeline_state()
    stop_horizontal_timeline_overlay()

def workspace_activated_handler(args):
    #eventArgs = adsk.core.WorkspaceEventArgs.cast(args)
    global document_transitioning

    active_workspace_id = get_active_workspace_id()
    debug_log(f'workspace activated id="{active_workspace_id}"')
    if active_workspace_id == 'FusionSolidEnvironment':
        document_transitioning = False
        if get_enabled():
            show_palette()
    else:
        # Deactivate
        document_transitioning = True
        reset_timeline_state()
        hide_palette()

def document_activating_handler(args):
    global document_transitioning

    debug_log('document activating')
    document_transitioning = True
    reset_timeline_state()

def document_deactivating_handler(args):
    global document_transitioning

    debug_log('document deactivating')
    document_transitioning = True
    reset_timeline_state()

def document_activated_handler(args):
    #eventArgs = adsk.core.DocumentEventArgs.cast(args)
    global document_transitioning
    global active_document_key

    active_workspace_id = get_active_workspace_id()
    debug_log(f'document activated workspace id="{active_workspace_id}"')
    if active_workspace_id == 'FusionSolidEnvironment':
        document_transitioning = False
        active_document_key = get_active_document_key()
        if get_enabled():
            show_palette()
            schedule_initial_palette_refresh()

def document_closing_handler(args):
    global document_transitioning

    debug_log('document closing')
    document_transitioning = True
    reset_timeline_state()
    stop_horizontal_timeline_overlay()

def document_closed_handler(args):
    global document_transitioning
    global timeline_item_count
    global timeline_marker_position

    debug_log('document closed')
    document_transitioning = True
    reset_timeline_state()

#########################################################################################
