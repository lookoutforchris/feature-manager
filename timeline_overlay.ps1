[CmdletBinding()]
param(
    [int]$OverlayHeight = 44,
    [int]$BottomInset = 0,
    [string]$TimelineResourceFolder = "",
    [string]$FusionDeployFolder = ""
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;

public static class FeatureManagerOverlayDisplayMetrics
{
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);
}
'@

$script:rootDir = Split-Path -Parent $PSCommandPath
$script:actionsDir = Join-Path $script:rootDir "overlay-actions"
$script:statePath = Join-Path $script:rootDir "overlay_state.json"
$script:currentState = @{
    markerPosition = -1
    timelineCount = -1
    suppressedCount = 0
    selectedPosition = -1
    search = ""
    filters = @()
}
$script:filterButtons = @{}
$script:isUpdatingFromState = $false
$script:isPlaying = $false

$mutexName = "Local\FeatureManagerHorizontalTimelineOverlay"
$createdMutex = $false
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdMutex)
if (-not $createdMutex) {
    return
}

function Get-DisplayScale {
    $physicalScreenWidth = [FeatureManagerOverlayDisplayMetrics]::GetSystemMetrics(0)
    $physicalScreenHeight = [FeatureManagerOverlayDisplayMetrics]::GetSystemMetrics(1)

    [pscustomobject]@{
        X = [System.Windows.SystemParameters]::PrimaryScreenWidth / $physicalScreenWidth
        Y = [System.Windows.SystemParameters]::PrimaryScreenHeight / $physicalScreenHeight
    }
}

function Get-FusionWindow {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $windows = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition
    )

    for ($i = 0; $i -lt $windows.Count; $i++) {
        $element = $windows.Item($i)
        if ($element.Current.ClassName -eq "Nu::QTMainWindow" -and
            $element.Current.Name -like "*Fusion*") {
            return $element
        }
    }

    return $null
}

function Set-OverlayBounds {
    param(
        [System.Windows.Window]$Window,
        [System.Windows.Automation.AutomationElement]$FusionWindow
    )

    $scale = Get-DisplayScale
    $fusionRect = $FusionWindow.Current.BoundingRectangle
    $Window.Left = $fusionRect.X * $scale.X
    $Window.Top = (($fusionRect.Y + $fusionRect.Height) * $scale.Y) - $OverlayHeight - $BottomInset
    $Window.Width = $fusionRect.Width * $scale.X
    $Window.Height = $OverlayHeight
}

function New-Brush {
    param([byte]$R, [byte]$G, [byte]$B)
    New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.Color]::FromRgb($R, $G, $B))
}

function Get-TimelineIconPath {
    param(
        [string]$IconName,
        [string]$FileName = "16x16.png"
    )

    if (-not $TimelineResourceFolder) {
        return $null
    }

    $path = Join-Path $TimelineResourceFolder "$IconName\$FileName"
    if (Test-Path -LiteralPath $path) {
        return $path
    }

    return $null
}

function Get-FusionIconPath {
    param([string]$RelativePath)

    if (-not $FusionDeployFolder -or -not $RelativePath) {
        return $null
    }

    $path = Join-Path $FusionDeployFolder "$RelativePath\16x16.png"
    if (Test-Path -LiteralPath $path) {
        return $path
    }

    return $null
}

function New-IconImage {
    param([string]$Path)

    if (-not $Path) {
        return $null
    }

    $bitmap = New-Object System.Windows.Media.Imaging.BitmapImage
    $bitmap.BeginInit()
    $bitmap.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bitmap.UriSource = New-Object System.Uri($Path, [System.UriKind]::Absolute)
    $bitmap.EndInit()
    $bitmap.Freeze()

    $image = New-Object System.Windows.Controls.Image
    $image.Source = $bitmap
    $image.Width = 16
    $image.Height = 16
    $image.Stretch = [System.Windows.Media.Stretch]::Uniform
    return $image
}

function Send-OverlayAction {
    param(
        [string]$Action,
        [hashtable]$Data = @{}
    )

    if (-not (Test-Path -LiteralPath $script:actionsDir)) {
        New-Item -ItemType Directory -Path $script:actionsDir -Force | Out-Null
    }

    $payload = [ordered]@{
        action = $Action
        data = $Data
        createdUtc = [DateTime]::UtcNow.ToString("o")
    }
    $path = Join-Path $script:actionsDir "$([Guid]::NewGuid().ToString('N')).json"
    $payload | ConvertTo-Json -Depth 6 -Compress | Set-Content -LiteralPath $path -Encoding UTF8
}

function Send-FilterState {
    if ($script:isUpdatingFromState) {
        return
    }

    $filters = @()
    foreach ($key in $script:filterButtons.Keys) {
        if ($script:filterButtons[$key].IsChecked) {
            $filters += $key
        }
    }

    Send-OverlayAction "featureFilters.changed" @{
        search = $script:searchBox.Text
        filters = $filters
    }
}

function New-BarButton {
    param(
        [string]$Text,
        [string]$ToolTip,
        [scriptblock]$Click,
        [string]$IconName = ""
    )

    $button = New-Object System.Windows.Controls.Button
    $iconPath = Get-TimelineIconPath $IconName
    $icon = New-IconImage $iconPath
    if ($icon) {
        $button.Content = $icon
    } else {
        $button.Content = $Text
    }
    $button.ToolTip = $ToolTip
    $button.MinWidth = 28
    $button.Height = 28
    $button.Margin = New-Object System.Windows.Thickness 2,0,2,0
    $button.Padding = New-Object System.Windows.Thickness 6,0,6,0
    $button.Background = New-Brush 59 68 80
    $button.BorderBrush = New-Brush 112 126 146
    $button.Foreground = New-Brush 231 236 244
    $button.Add_Click($Click)
    return $button
}

function New-FilterButton {
    param(
        [string]$Key,
        [string]$Text,
        [string]$IconPath
    )

    $button = New-Object System.Windows.Controls.Primitives.ToggleButton
    $icon = New-IconImage $IconPath
    if ($icon) {
        $button.Content = $icon
    } else {
        $button.Content = $Text
    }
    $button.ToolTip = "Filter $Text features"
    $button.MinWidth = 28
    $button.Height = 28
    $button.Margin = New-Object System.Windows.Thickness 2,0,2,0
    $button.Padding = New-Object System.Windows.Thickness 6,0,6,0
    $button.Background = New-Brush 59 68 80
    $button.BorderBrush = New-Brush 112 126 146
    $button.Foreground = New-Brush 231 236 244
    $button.Add_Checked({ Send-FilterState })
    $button.Add_Unchecked({ Send-FilterState })
    $script:filterButtons[$Key] = $button
    return $button
}

function Update-StatusText {
    $marker = [int]$script:currentState.markerPosition
    $count = [int]$script:currentState.timelineCount
    $suppressed = [int]$script:currentState.suppressedCount
    $selected = [int]$script:currentState.selectedPosition

    if ($count -lt 0) {
        $script:statusText.Text = "No parametric timeline"
        return
    }

    $position = $marker
    if ($selected -gt 0) {
        $position = $selected
    }

    $script:statusText.Text = "Feature $position of $count   -   $suppressed Features Suppressed"
}

function Read-OverlayState {
    if (-not (Test-Path -LiteralPath $script:statePath)) {
        Update-StatusText
        return
    }

    try {
        $state = Get-Content -LiteralPath $script:statePath -Raw | ConvertFrom-Json
    } catch {
        return
    }

    $script:currentState.markerPosition = [int]$state.markerPosition
    $script:currentState.timelineCount = [int]$state.timelineCount
    $script:currentState.suppressedCount = [int]$state.suppressedCount
    $script:currentState.selectedPosition = [int]$state.selectedPosition
    $script:currentState.search = [string]$state.search
    $script:currentState.filters = @($state.filters)

    $script:isUpdatingFromState = $true
    try {
        if ($script:searchBox.Text -ne $script:currentState.search) {
            $script:searchBox.Text = $script:currentState.search
        }
        foreach ($key in $script:filterButtons.Keys) {
            $script:filterButtons[$key].IsChecked = $script:currentState.filters -contains $key
        }
    } finally {
        $script:isUpdatingFromState = $false
    }

    Update-StatusText
}

function Set-Playing {
    param([bool]$Playing)
    $script:isPlaying = $Playing
    $iconName = if ($Playing) { "StopPlay" } else { "RollPlay" }
    $icon = New-IconImage (Get-TimelineIconPath $iconName)
    if ($icon) {
        $script:playButton.Content = $icon
    } else {
        $script:playButton.Content = if ($Playing) { "Stop" } else { "Play" }
    }
}

$fusionWindow = Get-FusionWindow
if (-not $fusionWindow) {
    throw "Fusion top-level UI Automation window was not found."
}

$ownerHandle = [IntPtr]$fusionWindow.Current.NativeWindowHandle

$window = New-Object System.Windows.Window
$window.WindowStyle = [System.Windows.WindowStyle]::None
$window.ResizeMode = [System.Windows.ResizeMode]::NoResize
$window.ShowInTaskbar = $false
$window.ShowActivated = $false
$window.Topmost = $false
$window.Background = [System.Windows.Media.Brushes]::Transparent
$window.AllowsTransparency = $true

$border = New-Object System.Windows.Controls.Border
$border.Background = New-Brush 59 68 80
$border.BorderBrush = New-Brush 86 97 113
$border.BorderThickness = New-Object System.Windows.Thickness 1
$border.Padding = New-Object System.Windows.Thickness 10,6,10,6

$layout = New-Object System.Windows.Controls.Grid
$layout.ColumnDefinitions.Add((New-Object System.Windows.Controls.ColumnDefinition -Property @{ Width = [System.Windows.GridLength]::Auto }))
$layout.ColumnDefinitions.Add((New-Object System.Windows.Controls.ColumnDefinition -Property @{ Width = [System.Windows.GridLength]::Auto }))
$layout.ColumnDefinitions.Add((New-Object System.Windows.Controls.ColumnDefinition -Property @{ Width = [System.Windows.GridLength]::Auto }))
$layout.ColumnDefinitions.Add((New-Object System.Windows.Controls.ColumnDefinition -Property @{ Width = New-Object System.Windows.GridLength 1, ([System.Windows.GridUnitType]::Star) }))

$transportPanel = New-Object System.Windows.Controls.StackPanel
$transportPanel.Orientation = [System.Windows.Controls.Orientation]::Horizontal
$transportPanel.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
$transportPanel.Children.Add((New-BarButton "|<" "Roll to beginning" { Send-OverlayAction "timeline.begin" } "RollBegin")) | Out-Null
$transportPanel.Children.Add((New-BarButton "<" "Previous feature" { Send-OverlayAction "timeline.previous" } "RollBack")) | Out-Null
$script:playButton = New-BarButton "Play" "Play through timeline" {
    Set-Playing (-not $script:isPlaying)
} "RollPlay"
$transportPanel.Children.Add($script:playButton) | Out-Null
$transportPanel.Children.Add((New-BarButton ">" "Next feature" { Send-OverlayAction "timeline.next" } "RollFwd")) | Out-Null
$transportPanel.Children.Add((New-BarButton ">|" "Roll to end" { Send-OverlayAction "timeline.end" } "RollEnd")) | Out-Null
[System.Windows.Controls.Grid]::SetColumn($transportPanel, 0)
$layout.Children.Add($transportPanel) | Out-Null

$filterPanel = New-Object System.Windows.Controls.StackPanel
$filterPanel.Orientation = [System.Windows.Controls.Orientation]::Horizontal
$filterPanel.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
$filterPanel.Margin = New-Object System.Windows.Thickness 14,0,8,0

$filterLabel = New-Object System.Windows.Controls.TextBlock
$filterLabel.Text = "Filters:"
$filterLabel.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
$filterLabel.Foreground = New-Brush 231 236 244
$filterLabel.Margin = New-Object System.Windows.Thickness 0,0,6,0
$filterPanel.Children.Add($filterLabel) | Out-Null

$filterPanel.Children.Add((New-FilterButton "sketch" "Sketch" (Get-FusionIconPath "Fusion\UI\FusionUI\Resources\sketch\Sketch_feature"))) | Out-Null
$filterPanel.Children.Add((New-FilterButton "solid" "Solid" (Get-FusionIconPath "Fusion\UI\FusionUI\Resources\solid\extrude"))) | Out-Null
$filterPanel.Children.Add((New-FilterButton "construct" "Construction" (Get-FusionIconPath "Fusion\UI\FusionUI\Resources\construction\plane_offset"))) | Out-Null
$filterPanel.Children.Add((New-FilterButton "pattern" "Pattern" (Get-FusionIconPath "Fusion\UI\FusionUI\Resources\pattern\pattern_rectangular"))) | Out-Null
$filterPanel.Children.Add((New-FilterButton "assembly" "Assembly" (Get-FusionIconPath "Fusion\UI\FusionUI\Resources\Assembly\CreateComponentFromBody"))) | Out-Null
$filterPanel.Children.Add((New-FilterButton "suppressed" "Suppressed" (Get-TimelineIconPath "Eye" "16x16-disabled.png"))) | Out-Null
[System.Windows.Controls.Grid]::SetColumn($filterPanel, 1)
$layout.Children.Add($filterPanel) | Out-Null

$searchPanel = New-Object System.Windows.Controls.StackPanel
$searchPanel.Orientation = [System.Windows.Controls.Orientation]::Horizontal
$searchPanel.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
$searchPanel.Margin = New-Object System.Windows.Thickness 8,0,8,0

$searchLabel = New-Object System.Windows.Controls.TextBlock
$searchLabel.Text = "Search:"
$searchLabel.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
$searchLabel.Foreground = New-Brush 231 236 244
$searchLabel.Margin = New-Object System.Windows.Thickness 0,0,6,0
$searchPanel.Children.Add($searchLabel) | Out-Null

$script:searchBox = New-Object System.Windows.Controls.TextBox
$script:searchBox.Width = 240
$script:searchBox.Height = 28
$script:searchBox.Margin = New-Object System.Windows.Thickness 0,0,0,0
$script:searchBox.VerticalContentAlignment = [System.Windows.VerticalAlignment]::Center
$script:searchBox.ToolTip = "Search features"
$script:searchBox.Background = New-Brush 45 53 65
$script:searchBox.BorderBrush = New-Brush 112 126 146
$script:searchBox.Foreground = New-Brush 245 248 252
$script:searchBox.Add_TextChanged({ Send-FilterState })
$searchPanel.Children.Add($script:searchBox) | Out-Null
[System.Windows.Controls.Grid]::SetColumn($searchPanel, 2)
$layout.Children.Add($searchPanel) | Out-Null

$script:statusText = New-Object System.Windows.Controls.TextBlock
$script:statusText.HorizontalAlignment = [System.Windows.HorizontalAlignment]::Right
$script:statusText.VerticalAlignment = [System.Windows.VerticalAlignment]::Center
$script:statusText.Foreground = New-Brush 231 236 244
$script:statusText.FontSize = 13
$script:statusText.Text = "Feature 0 of 0   -   0 Features Suppressed"
[System.Windows.Controls.Grid]::SetColumn($script:statusText, 3)
$layout.Children.Add($script:statusText) | Out-Null

$border.Child = $layout
$window.Content = $border

$helper = New-Object System.Windows.Interop.WindowInteropHelper $window
$helper.Owner = $ownerHandle

Set-OverlayBounds $window $fusionWindow
Read-OverlayState

$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(500)
$timer.Add_Tick({
    $currentFusionWindow = Get-FusionWindow
    if (-not $currentFusionWindow) {
        $window.Close()
        return
    }

    Set-OverlayBounds $window $currentFusionWindow
    Read-OverlayState
})
$timer.Start()

$playTimer = New-Object System.Windows.Threading.DispatcherTimer
$playTimer.Interval = [TimeSpan]::FromMilliseconds(650)
$playTimer.Add_Tick({
    if (-not $script:isPlaying) {
        return
    }
    if ([int]$script:currentState.markerPosition -ge [int]$script:currentState.timelineCount) {
        Set-Playing $false
        return
    }
    Send-OverlayAction "timeline.next"
})
$playTimer.Start()

try {
    $window.ShowDialog() | Out-Null
} finally {
    $timer.Stop()
    $playTimer.Stop()
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
