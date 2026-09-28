$devices = adb devices |
    Select-String "\sdevice$" |
    ForEach-Object { ($_ -split "\s+")[0] }

foreach ($serial in $devices) {

    $model = (adb -s $serial shell getprop ro.product.model).Trim()

    $pnp = Get-PnpDevice -PresentOnly |
        Where-Object {
            $_.InstanceId -like "*$serial*"
        } |
        Select-Object -First 1

    if ($pnp) {
        $arrival = (Get-PnpDeviceProperty `
            -InstanceId $pnp.InstanceId `
            -KeyName "DEVPKEY_Device_LastArrivalDate").Data

        if ($arrival) {
            $duration = New-TimeSpan -Start $arrival -End (Get-Date)

            [PSCustomObject]@{
                ADB_ID          = $serial
                Model           = $model
                ConnectedSince  = $arrival
                ConnectedFor    = "{0}j {1}h {2}min" -f `
                                  $duration.Days,
                                  $duration.Hours,
                                  $duration.Minutes
            }
        }
    }
}