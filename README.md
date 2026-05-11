$filters += "--include=$($t.key)"


(($filters -join "`r`n") + "`r`n") | Set-Content -Path $outputFile -Encoding ascii
