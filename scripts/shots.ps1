# Walks the shot list in docs/shot-list.md one shot at a time.
#
#   .\scripts\shots.ps1            every shot, in order
#   .\scripts\shots.ps1 4          start at shot 4
#   .\scripts\shots.ps1 4 -Only    just shot 4
#
# For each shot: starts run.py with that shot's flags, opens the shot's URL in
# your default browser, and waits. Start recording, take the shot, press Enter,
# and it stops that run and starts the next. Nothing else may hold port 8765:
# stop any other run.py first (Ctrl+C, so its journey saves).
param([int]$Start = 1, [switch]$Only)

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$base = "http://127.0.0.1:8765/"

$shots = @(
    @{ n = 1; line = 'I got a fly brain to play Pokemon Red';            args = '--portrait --no-learn';              url = '?portrait=1' },
    @{ n = 2; line = 'neurons wired into PyBoy';                          args = '--portrait --no-learn';              url = '?portrait=1&view=4&clean=1' },
    @{ n = 3; line = 'I made this couch setup for him (orbit, then TV)';  args = '--portrait --no-learn';              url = '?portrait=1&view=1&clean=1' ; url2 = '?portrait=1&view=2&clean=1' },
    @{ n = 4; line = 'It took N to leave Red''s bedroom';                 args = '--replay left_bedroom --portrait';   url = '?portrait=1' },
    @{ n = 5; line = 'it hit the stairs and wandered Pallet Town';        args = '--replay left_house --portrait';     url = '?portrait=1' },
    @{ n = 6; line = 'before triggering Professor Oak';                   args = '--replay entered_lab --portrait';    url = '?portrait=1'; note = 'got_starter has no replay yet; entered_lab is the closest moment' },
    @{ n = 7; line = 'still waiting for him to pick his starter';         args = '--portrait --no-learn';              url = '?portrait=1&view=3&clean=1' },
    @{ n = 8; line = 'outro, comment Pokemon';                            args = '--portrait --no-learn';              url = '?portrait=1' }
)

if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Port 8765 is in use: another run.py is going. Ctrl+C it first (that saves its journey), then run this again."
    exit 1
}

foreach ($shot in $shots) {
    if ($shot.n -lt $Start) { continue }
    if ($Only -and $shot.n -ne $Start) { continue }
    Write-Host ""
    Write-Host ("=== shot {0}: ""{1}""" -f $shot.n, $shot.line)
    if ($shot.note) { Write-Host ("    note: " + $shot.note) }
    Write-Host ("    run.py " + $shot.args)
    Write-Host ("    " + $base + $shot.url)
    if ($shot.url2) { Write-Host ("    then " + $base + $shot.url2 + "  (open this for the second half)") }
    $args = "run.py --no-browser " + $shot.args
    $proc = Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $root -PassThru -NoNewWindow
    # Give the server a moment to bind before the browser asks for the page.
    $deadline = (Get-Date).AddSeconds(20)
    while (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    Start-Process ($base + $shot.url)
    if ($shot.args -like '*--replay*') { Write-Host "    the replay starts about 15 s before the moment: record NOW" }
    Read-Host "    press Enter when the take is done"
    # Stop-Process is not Ctrl+C: a --no-learn journey run has nothing to
    # save, and a replay never writes the journey, so nothing is lost.
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    Start-Sleep -Seconds 1
}
Write-Host ""
Write-Host "done. Recordings from Win+Alt+R land in Videos\Captures."
