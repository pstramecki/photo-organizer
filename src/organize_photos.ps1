<#
.SYNOPSIS
Organizes photos and videos from a source folder to a destination folder.
Photos -> DST\YYYY\MM
Videos -> DST\videos\YYYY
Detects duplicates and prints a summary.
Supports dry-run mode.
Windowed app: progress bar + live log, processing runs on a background
runspace so the UI stays responsive, with a Cancel button.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$ExifToolPath = "C:\Program Files\exiftool\exiftool.exe"
$photoExtensions = @('jpg','jpeg','png','heic','gif','tiff')
$videoExtensions = @('mp4','mov','avi','mkv','flv','wmv', '3gp')

# --- Create form ---
$form = New-Object System.Windows.Forms.Form
$form.Text = "Photo Organizer"
$form.ClientSize = New-Object System.Drawing.Size(640,560)
$form.MinimumSize = New-Object System.Drawing.Size(520,420)
$form.StartPosition = "CenterScreen"

# --- Input folder ---
$lblInput = New-Object System.Windows.Forms.Label
$lblInput.Text = "Input Folder:"
$lblInput.Location = New-Object System.Drawing.Point(15,20)
$lblInput.AutoSize = $true
$form.Controls.Add($lblInput)

$txtInput = New-Object System.Windows.Forms.TextBox
$txtInput.Location = New-Object System.Drawing.Point(120,18)
$txtInput.Size = New-Object System.Drawing.Size(400,20)
$txtInput.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$form.Controls.Add($txtInput)

$btnInput = New-Object System.Windows.Forms.Button
$btnInput.Text = "Browse"
$btnInput.Location = New-Object System.Drawing.Point(530,15)
$btnInput.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right
$btnInput.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq "OK") { $txtInput.Text = $dialog.SelectedPath }
})
$form.Controls.Add($btnInput)

# --- Output folder ---
$lblOutput = New-Object System.Windows.Forms.Label
$lblOutput.Text = "Output Folder:"
$lblOutput.Location = New-Object System.Drawing.Point(15,60)
$lblOutput.AutoSize = $true
$form.Controls.Add($lblOutput)

$txtOutput = New-Object System.Windows.Forms.TextBox
$txtOutput.Location = New-Object System.Drawing.Point(120,58)
$txtOutput.Size = New-Object System.Drawing.Size(400,20)
$txtOutput.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$form.Controls.Add($txtOutput)

$btnOutput = New-Object System.Windows.Forms.Button
$btnOutput.Text = "Browse"
$btnOutput.Location = New-Object System.Drawing.Point(530,55)
$btnOutput.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right
$btnOutput.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq "OK") { $txtOutput.Text = $dialog.SelectedPath }
})
$form.Controls.Add($btnOutput)

# --- Operation (Copy / Move) ---
$lblOp = New-Object System.Windows.Forms.Label
$lblOp.Text = "Operation:"
$lblOp.Location = New-Object System.Drawing.Point(15,100)
$lblOp.AutoSize = $true
$form.Controls.Add($lblOp)

$radioCopy = New-Object System.Windows.Forms.RadioButton
$radioCopy.Text = "Copy"
$radioCopy.Location = New-Object System.Drawing.Point(120,98)
$radioCopy.AutoSize = $true
$radioCopy.Checked = $true
$form.Controls.Add($radioCopy)

$radioMove = New-Object System.Windows.Forms.RadioButton
$radioMove.Text = "Move"
$radioMove.Location = New-Object System.Drawing.Point(220,98)
$radioMove.AutoSize = $true
$form.Controls.Add($radioMove)

# --- Dry Run ---
$chkDryRun = New-Object System.Windows.Forms.CheckBox
$chkDryRun.Text = "Dry Run (no files will be moved/copied)"
$chkDryRun.Location = New-Object System.Drawing.Point(320,99)
$chkDryRun.AutoSize = $true
$form.Controls.Add($chkDryRun)

# --- Action buttons ---
$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = "Start"
$btnStart.Location = New-Object System.Drawing.Point(120,135)
$btnStart.Size = New-Object System.Drawing.Size(90,28)
$form.Controls.Add($btnStart)

$btnCancel = New-Object System.Windows.Forms.Button
$btnCancel.Text = "Cancel"
$btnCancel.Location = New-Object System.Drawing.Point(220,135)
$btnCancel.Size = New-Object System.Drawing.Size(90,28)
$btnCancel.Enabled = $false
$form.Controls.Add($btnCancel)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "Close"
$btnClose.Location = New-Object System.Drawing.Point(320,135)
$btnClose.Size = New-Object System.Drawing.Size(90,28)
$form.Controls.Add($btnClose)

# --- Progress bar + status ---
$progressBar = New-Object System.Windows.Forms.ProgressBar
$progressBar.Location = New-Object System.Drawing.Point(15,180)
$progressBar.Size = New-Object System.Drawing.Size(605,20)
$progressBar.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$form.Controls.Add($progressBar)

$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "Idle"
$lblStatus.Location = New-Object System.Drawing.Point(15,205)
$lblStatus.AutoSize = $true
$lblStatus.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left
$form.Controls.Add($lblStatus)

# --- Log ---
$lblLog = New-Object System.Windows.Forms.Label
$lblLog.Text = "Log:"
$lblLog.Location = New-Object System.Drawing.Point(15,230)
$lblLog.AutoSize = $true
$form.Controls.Add($lblLog)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Location = New-Object System.Drawing.Point(15,250)
$txtLog.Size = New-Object System.Drawing.Size(605,290)
$txtLog.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right -bor [System.Windows.Forms.AnchorStyles]::Bottom
$txtLog.Multiline = $true
$txtLog.ScrollBars = "Vertical"
$txtLog.ReadOnly = $true
$txtLog.Font = New-Object System.Drawing.Font("Consolas", 9)
$form.Controls.Add($txtLog)

# --- Helpers that run on the UI thread ---
function Set-RunningState {
    param([bool]$Running)
    $txtInput.Enabled = -not $Running
    $txtOutput.Enabled = -not $Running
    $btnInput.Enabled = -not $Running
    $btnOutput.Enabled = -not $Running
    $radioCopy.Enabled = -not $Running
    $radioMove.Enabled = -not $Running
    $chkDryRun.Enabled = -not $Running
    $btnStart.Enabled = -not $Running
    $btnCancel.Enabled = $Running
}

function Stop-Worker {
    if ($script:timer) { $script:timer.Stop() }
    if ($script:PowerShell) {
        try { $script:PowerShell.Stop() } catch {}
        try { $script:PowerShell.Dispose() } catch {}
    }
    if ($script:Runspace) {
        try { $script:Runspace.Close() } catch {}
        try { $script:Runspace.Dispose() } catch {}
    }
    $script:PowerShell = $null
    $script:Runspace = $null
    $script:AsyncResult = $null
}

# --- Worker script block: runs on a background runspace ---
$workerScript = {
    param($SourceDir, $DestDir, $Operation, $DryRun, $ExifToolPath, $photoExtensions, $videoExtensions, $sync)

    function Log($msg) { $sync.Log.Enqueue($msg) }

    function Get-FileDate {
        param($File)
        $exifDate = $null
        try {
            $exifData = & "$ExifToolPath" -s3 -DateTimeOriginal "`"$File`"" 2>$null
            if ($exifData) {
                $fixed = $exifData -replace '^(\d{4}):(\d{2}):(\d{2})','${1}-${2}-${3}'
                $exifDate = Get-Date $fixed
            }
        } catch {}

        if ($exifDate) {
            return @{ Date=$exifDate; ExifUsed=$true }
        } else {
            $mtime = (Get-Item $File).LastWriteTime
            return @{ Date=$mtime; ExifUsed=$false }
        }
    }

    try {
        $hashDbPath = Join-Path $DestDir "hashes.json"
        $hashTable = @{}
        if (Test-Path $hashDbPath) {
            try {
                $json = Get-Content $hashDbPath -Raw
                if ($json -and $json.Trim().Length -gt 0) {
                    $loaded = $json | ConvertFrom-Json
                    $hashTable = @{}
                    foreach ($prop in $loaded.PSObject.Properties) {
                        $hashTable[$prop.Name] = $prop.Value
                    }
                    Log "[Info] Loaded existing hash table from $hashDbPath"
                }
            } catch {
                Log "[Warning] Could not load hash table. Starting fresh."
                $hashTable = @{}
            }
        }

        $Total = 0; $ExifUsed = 0; $MTimeUsed = 0; $Videos = 0; $Duplicates = 0; $Unrecognized = 0

        if (-not (Test-Path $DestDir) -and -not $DryRun) {
            New-Item -Path $DestDir -ItemType Directory | Out-Null
        } elseif ($DryRun -and -not (Test-Path $DestDir)) {
            Log "[DryRun] Would create destination folder: $DestDir"
        }

        $files = @(Get-ChildItem -Path $SourceDir -Recurse -File)
        $sync.Total = $files.Count

        for ($i = 0; $i -lt $files.Count; $i++) {
            if ($sync.Cancelled) {
                Log "[Cancelled] Stopping before processing remaining files."
                break
            }

            $item = $files[$i]
            $Total++
            $file = $item.FullName
            $ext = $item.Extension.TrimStart('.').ToLower()

            if ($videoExtensions -contains $ext) {
                $dateInfo = Get-FileDate $file
                $year = $dateInfo.Date.ToString('yyyy')
                $destFolder = Join-Path $DestDir "videos\$year"
                $Videos++
            } elseif ($photoExtensions -contains $ext) {
                $dateInfo = Get-FileDate $file
                $year = $dateInfo.Date.ToString('yyyy')
                $month = $dateInfo.Date.ToString('MM')
                $destFolder = Join-Path $DestDir "$year\$month"
                if ($dateInfo.ExifUsed) { $ExifUsed++ } else { $MTimeUsed++ }
            } else {
                Log "[Skipped - unknown extension] $file (.$ext)"
                $Unrecognized++
                $sync.Progress = $i + 1
                continue
            }

            $hash = Get-FileHash -Path $file -Algorithm SHA256
            if ($hashTable.ContainsKey($hash.Hash)) {
                Log "[Duplicate] $file"
                $Duplicates++
                $sync.Progress = $i + 1
                continue
            }
            $hashTable[$hash.Hash] = $true

            if (-not (Test-Path $destFolder)) {
                if ($DryRun) {
                    Log "[DryRun] Would create folder: $destFolder"
                } else {
                    New-Item -Path $destFolder -ItemType Directory | Out-Null
                }
            }

            $baseName = $item.Name
            $destPath = Join-Path $destFolder $baseName
            while (Test-Path $destPath) {
                $destPath = Join-Path $destFolder ("{0}_{1}{2}" -f $item.BaseName, (Get-Random -Maximum 10000), $item.Extension)
            }

            if ($DryRun) {
                if ($Operation -eq "Move") { Log "[DryRun] Would move: $file -> $destPath" }
                else { Log "[DryRun] Would copy: $file -> $destPath" }
            } else {
                if ($Operation -eq "Move") {
                    Move-Item -Path $file -Destination $destPath
                    Log "[Moved] $file -> $destPath"
                } else {
                    Copy-Item -Path $file -Destination $destPath
                    Log "[Copied] $file -> $destPath"
                }
            }

            $sync.Progress = $i + 1
        }

        Log ""
        Log "============= Summary ============="
        Log "Total files processed : $Total"
        Log "Duplicates skipped    : $Duplicates"
        Log "Photos using EXIF     : $ExifUsed"
        Log "Photos using mtime    : $MTimeUsed"
        Log "Videos                : $Videos"
        Log "Unrecognized          : $Unrecognized"
        Log "Dry run mode          : $DryRun"
        Log "Cancelled             : $($sync.Cancelled)"
        Log "===================================="

        if (-not $DryRun) {
            try {
                $hashTable | ConvertTo-Json -Depth 3 | Set-Content -Path $hashDbPath -Encoding UTF8
                Log "[Info] Saved hash table to $hashDbPath"
            } catch {
                Log "[Error] Failed to save hash table: $_"
            }
        } else {
            Log "[DryRun] Would save hash table to $hashDbPath"
        }
    } catch {
        $sync.Log.Enqueue("[Error] $_")
    } finally {
        $sync.Done = $true
    }
}

# --- Start button: launch the worker on a background runspace ---
$btnStart.Add_Click({
    if (-not (Test-Path $txtInput.Text)) {
        [System.Windows.Forms.MessageBox]::Show("Input folder does not exist.","Error","OK","Error")
        return
    }
    if (-not (Test-Path $txtOutput.Text)) {
        try { New-Item -ItemType Directory -Path $txtOutput.Text | Out-Null }
        catch { [System.Windows.Forms.MessageBox]::Show("Cannot create output folder.","Error","OK","Error"); return }
    }

    $SourceDir = $txtInput.Text
    $DestDir = $txtOutput.Text
    $Operation = if ($radioCopy.Checked) { "Copy" } else { "Move" }
    $DryRun = $chkDryRun.Checked

    $txtLog.Clear()
    $progressBar.Value = 0
    $progressBar.Style = "Marquee"
    $lblStatus.Text = "Starting..."
    Set-RunningState -Running $true

    $script:sync = [hashtable]::Synchronized(@{
        Log       = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
        Progress  = 0
        Total     = 0
        Done      = $false
        Cancelled = $false
    })

    $script:Runspace = [runspacefactory]::CreateRunspace()
    $script:Runspace.Open()
    $script:PowerShell = [powershell]::Create()
    $script:PowerShell.Runspace = $script:Runspace
    [void]$script:PowerShell.AddScript($workerScript).
        AddArgument($SourceDir).
        AddArgument($DestDir).
        AddArgument($Operation).
        AddArgument($DryRun).
        AddArgument($ExifToolPath).
        AddArgument($photoExtensions).
        AddArgument($videoExtensions).
        AddArgument($script:sync)
    $script:AsyncResult = $script:PowerShell.BeginInvoke()

    $script:timer = New-Object System.Windows.Forms.Timer
    $script:timer.Interval = 150
    $script:timer.Add_Tick({
        $msg = $null
        while ($script:sync.Log.TryDequeue([ref]$msg)) {
            $txtLog.AppendText("$msg`r`n")
        }

        if ($script:sync.Total -gt 0) {
            if ($progressBar.Style -ne "Blocks") {
                $progressBar.Style = "Blocks"
                $progressBar.Maximum = $script:sync.Total
            }
            $progressBar.Value = [Math]::Min($script:sync.Progress, $script:sync.Total)
            $lblStatus.Text = "Processing: $($script:sync.Progress) / $($script:sync.Total)"
        }

        if ($script:sync.Done) {
            $lblStatus.Text = if ($script:sync.Cancelled) { "Cancelled" } else { "Completed" }
            $progressBar.Style = "Blocks"
            Set-RunningState -Running $false
            Stop-Worker
        }
    })
    $script:timer.Start()
})

# --- Cancel button: signal the worker to stop after the current file ---
$btnCancel.Add_Click({
    if ($script:sync) {
        $script:sync.Cancelled = $true
        $btnCancel.Enabled = $false
        $lblStatus.Text = "Cancelling..."
    }
})

# --- Close button ---
$btnClose.Add_Click({ $form.Close() })

# --- Make sure the background runspace doesn't outlive the window ---
$form.Add_FormClosing({
    if ($script:sync) { $script:sync.Cancelled = $true }
    Stop-Worker
})

# --- Show form ---
[void]$form.ShowDialog()
