' TVBox 三个本机网关：8080 spankbang / 8081 sexkbj / 8082 erome
' 已在跑的会自动跳过（每个 python 发现端口占用会以 100 退出）
Option Explicit
Dim sh, base, repo, fso
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = "C:\Users\plsharevme\tvbox-gateway\"
repo = "C:\Users\plsharevme\tvbox-repo"

sh.Run "cmd /c """ & base & "start.cmd""", 0, False
WScript.Sleep 1500
sh.Run "cmd /c """ & base & "start-sexkbj.cmd""", 0, False
WScript.Sleep 1500
sh.Run "cmd /c """ & base & "start-erome.cmd""", 0, False

' 等三个端口都应答（最多 90 秒），然后把这个 IP 同步进配置并 push
Dim i, ready
ready = False
For i = 1 To 30
  WScript.Sleep 3000
  If PortsUp() Then
    ready = True
    Exit For
  End If
Next

If ready And fso.FolderExists(repo & "\.git") Then
  sh.CurrentDirectory = repo
  sh.Run "cmd /c node tools\update-gateway-ip.mjs --push > """ & base & "last-ip-sync.log"" 2>&1", 0, True
End If

Function PortsUp()
  Dim ports, p, ok
  ports = Array(8080, 8081, 8082)
  ok = True
  On Error Resume Next
  For Each p In ports
    Dim http
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 2000, 2000, 4000, 4000
    http.open "GET", "http://127.0.0.1:" & p & "/", False
    http.send
    If Err.Number <> 0 Or http.Status <> 200 Then ok = False
    Err.Clear
  Next
  On Error Goto 0
  PortsUp = ok
End Function
