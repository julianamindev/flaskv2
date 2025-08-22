param(
  [string]$Prefix = 'PSSC-'   # Name prefix to filter
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'
try { Import-Module ScheduledTasks -ErrorAction Stop } catch { }
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'

function PrettyISO($iso){
  if(-not $iso){ return '' }
  if($iso -match '^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$'){
    $parts=@(); if($Matches[1]){$parts+=("$($Matches[1])h")}
                if($Matches[2]){$parts+=("$($Matches[2])m")}
                if($Matches[3]){$parts+=("$($Matches[3])s")}
    return ($parts -join ' ')
  } else { return $iso }
}
function JoinLocalNames($nodes){ if(-not $nodes){return ''}; ($nodes | ForEach-Object {$_.LocalName}) -join ', ' }
function JoinInnerText($nodes){ if(-not $nodes){return ''}; ($nodes | ForEach-Object {$_.InnerText}) -join ', ' }

function DescribeFromXml($xml){
  $nsm = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
  $nsm.AddNamespace('t', $ns)
  $descs = @()

  foreach($n in $xml.SelectNodes('//t:Triggers/*', $nsm)){
    if ($n.LocalName -eq 'CalendarTrigger') {
      $start = [datetime]$n.SelectSingleNode('t:StartBoundary',$nsm).InnerText
      $time  = $start.ToString('HH:mm')

      if ($n.SelectSingleNode('t:ScheduleByMonth',$nsm)) {
        $isLast = $false
        if ($n.SelectSingleNode('t:ScheduleByMonth/t:DaysOfMonth/t:LastDayOfMonth',$nsm)) { $isLast = $true }
        foreach ($d in $n.SelectNodes('t:ScheduleByMonth/t:DaysOfMonth/t:Day',$nsm)) { if ($d.InnerText -eq 'Last') { $isLast = $true } }
        if ($isLast) { $dom = 'last day of month' }
        else {
          $dom = (JoinInnerText ($n.SelectNodes('t:ScheduleByMonth/t:DaysOfMonth/t:Day',$nsm)))
          if (-not $dom) { $dom = 'days' }
        }
        $descs += "Monthly on $dom at $time"
      }
      elseif ($n.SelectSingleNode('t:ScheduleByDay',$nsm)) {
        $ivn = $n.SelectSingleNode('t:ScheduleByDay/t:DaysInterval',$nsm)
        $ival = if($ivn){ [int]$ivn.InnerText } else { 1 }
        if ($ival -gt 1) { $descs += "Every $ival days at $time" } else { $descs += "Every day at $time" }
      }
      elseif ($n.SelectSingleNode('t:ScheduleByWeek',$nsm)) {
        $days = JoinLocalNames ($n.SelectNodes('t:ScheduleByWeek/t:DaysOfWeek/*',$nsm)); if(-not $days){ $days='—' }
        $wNode = $n.SelectSingleNode('t:ScheduleByWeek/t:WeeksInterval',$nsm)
        $w = if($wNode){ [int]$wNode.InnerText } else { 1 }
        if ($w -gt 1) { $descs += "Weekly on $days at $time (every $w weeks)" } else { $descs += "Weekly on $days at $time" }
      }
      elseif ($n.SelectSingleNode('t:ScheduleByMonthDayOfWeek',$nsm)) {
        $weeks = JoinLocalNames ($n.SelectNodes('t:ScheduleByMonthDayOfWeek/t:Weeks/*',$nsm)); if(-not $weeks){ $weeks='weeks' }
        $days  = JoinLocalNames ($n.SelectNodes('t:ScheduleByMonthDayOfWeek/t:DaysOfWeek/*',$nsm)); if(-not $days){ $days='days' }
        $descs += "Monthly on $weeks $days at $time"
      }
      else { $descs += 'Calendar trigger' }

      $rep = $n.SelectSingleNode('t:Repetition/t:Interval',$nsm)
      if ($rep) { $descs[$descs.Count-1] += ', every ' + (PrettyISO $rep.InnerText) }
    }
    elseif ($n.LocalName -eq 'TimeTrigger') { $descs += ('Once at ' + ([datetime]$n.SelectSingleNode('t:StartBoundary',$nsm).InnerText).ToString('yyyy-MM-dd HH:mm')) }
    elseif ($n.LocalName -eq 'BootTrigger') { $descs += 'At startup' }
    elseif ($n.LocalName -eq 'LogonTrigger') { $descs += 'At logon' }
    elseif ($n.LocalName -eq 'IdleTrigger')  { $descs += 'On idle' }
    else { $descs += $n.LocalName }
  }
  if($descs.Count -eq 0){ '—' } else { $descs -join ' | ' }
}

function DescribeFromCim($t){
  $descs = @()
  foreach($trig in $t.Triggers){
    $cls = $trig.CimClass.CimClassName
    $start = [datetime]$trig.StartBoundary
    $time = $start.ToString('HH:mm')
    switch ($cls) {
      'MSFT_TaskDailyTrigger'   { $n = [int]$trig.DaysInterval; if ($n -gt 1) { $descs += "Every $n days at $time" } else { $descs += "Every day at $time" } }
      'MSFT_TaskWeeklyTrigger'  {
        $s = $trig.DaysOfWeek.ToString()
        $names='Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'
        $picked=@(); foreach($n in $names){ if($s -like "*$n*"){ $picked += $n } }
        $days = ($picked -join ', '); if(-not $days){ $days='—' }
        $w = [int]$trig.WeeksInterval
        if ($w -gt 1) { $descs += "Weekly on $days at $time (every $w weeks)" } else { $descs += "Weekly on $days at $time" }
      }
      'MSFT_TaskMonthlyTrigger' { if($trig.RunOnLastDayOfMonth){ $dom='last day of month' } else { $dom = ($trig.DaysOfMonth -join ', ') }; if(-not $dom){ $dom='days' }; $descs += "Monthly on $dom at $time" }
      'MSFT_TaskMonthlyDOWTrigger' {
        $w = $trig.WeeksOfMonth.ToString(); if(-not $w){ $w = $trig.WhichWeeks.ToString() }
        $weeks = ($w -replace '\s+',''); if(-not $weeks){ $weeks='weeks' }
        $s = $trig.DaysOfWeek.ToString()
        $names='Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'
        $picked=@(); foreach($n in $names){ if($s -like "*$n*"){ $picked += $n } }
        $days = ($picked -join ', '); if(-not $days){ $days='days' }
        $descs += "Monthly on $weeks $days at $time"
      }
      'MSFT_TaskTimeTrigger'    { $descs += ("Once at " + $start.ToString('yyyy-MM-dd HH:mm')) }
      'MSFT_TaskBootTrigger'    { $descs += 'At startup' }
      'MSFT_TaskLogonTrigger'   { $descs += 'At logon' }
      'MSFT_TaskIdleTrigger'    { $descs += 'On idle' }
      default                   { $descs += $cls }
    }
    if($trig.Repetition -and $trig.Repetition.Interval){
      $descs[$descs.Count-1] += ', every ' + (PrettyISO $trig.Repetition.Interval)
    }
  }
  if($descs.Count -eq 0){ '—' } else { $descs -join ' | ' }
}

$tasks = Get-ScheduledTask -TaskName "$Prefix*" -ErrorAction SilentlyContinue
if (-not $tasks) { @() | ConvertTo-Json -Depth 4; exit }


$codeMap = @{
  0       = 'success'          # 0x0
  1       = 'error'           # generic schtasks 0x1
  267009  = 'ready'            # 0x41301
  267010  = 'running'          # 0x41302
  267011  = 'not yet run'      # 0x41303
  267012  = 'no more runs'     # 0x41304
  267014  = 'stopped by user'  # 0x41306
  267015  = 'no triggers/disabled' # 0x41307
}

$out = @()
foreach($t in $tasks){
  try {
    $info    = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop
    $xmlText = Export-ScheduledTask  -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop
    $xml     = New-Object System.Xml.XmlDocument
    $xml.LoadXml($xmlText)
    $regular = DescribeFromXml $xml
  } catch {
    $regular = DescribeFromCim $t
    $info    = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue
  }

  # precompute (no inline "if" in hashtable)
  $nextRunStr = ''; if ($info -and $info.NextRunTime) { $nextRunStr = $info.NextRunTime.ToString('yyyy-MM-dd HH:mm') }
  $lastRunStr = ''; if ($info -and $info.LastRunTime) { $lastRunStr = $info.LastRunTime.ToString('yyyy-MM-dd HH:mm') }
  # $lastRes    = $null; if ($info) { $lastRes = $info.LastTaskResult }
  $code       = if ($info) { [int]$info.LastTaskResult } else { $null }
  $neverRun   = ($info -and $info.LastRunTime -eq [datetime]::MinValue)
  $success =
    if ($neverRun) { 'not yet run' }
    elseif ($code -ne $null -and $codeMap.ContainsKey($code)) { $codeMap[$code] }
    elseif ($code -eq 0) { 'success' }
    elseif ($code -ne $null) { 'error' }   # anything nonzero that wasn't mapped
    else { 'unknown' }


  $out += [pscustomobject]@{
    Name           = $t.TaskName
    NameNoPrefix   = ($t.TaskName -replace ('^' + [regex]::Escape($Prefix)),'')
    Regularity     = $regular
    State          = $t.State.ToString()
    NextRun        = $nextRunStr
    LastRun        = $lastRunStr
    Success        = $success
  }
}

$out | ConvertTo-Json -Depth 4
