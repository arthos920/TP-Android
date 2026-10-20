adb shell monkey -p com.example.app -c android.intent.category.LAUNCHER 1

adb shell cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER com.example.app