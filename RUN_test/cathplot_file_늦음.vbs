' 빈 cmd 창없이 실행하기
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
objShell.Run """D:\CathPlot\dist\CathPlot.exe"""
' objShell.Run """D:\CathPlot\dist\CathPlot\CathPlot.exe"""