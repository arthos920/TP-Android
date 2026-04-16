Add-Type -AssemblyName System.Windows.Forms

Start-Process "ssh user@ip"
Start-Sleep 2
[System.Windows.Forms.SendKeys]::SendWait("monMotDePasse{ENTER}")