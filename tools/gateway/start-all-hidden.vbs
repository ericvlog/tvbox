' TVBox 三个本机网关：8080 spankbang / 8081 sexkbj / 8082 erome
Set sh = CreateObject("WScript.Shell")
base = "C:\Users\plsharevme\tvbox-gateway\"
sh.Run "cmd /c """ & base & "start.cmd""", 0, False
WScript.Sleep 1500
sh.Run "cmd /c """ & base & "start-sexkbj.cmd""", 0, False
WScript.Sleep 1500
sh.Run "cmd /c """ & base & "start-erome.cmd""", 0, False
