Get-ChildItem C:\ -Directory | 
ForEach-Object {
    $size = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    [PSCustomObject]@{
        Folder = $_.FullName
        SizeGB = [math]::Round($size / 1GB, 2)
    }
} | Sort-Object SizeGB -Descending