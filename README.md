# 0. Clean des attachments existants du ticket
$issueJson = & $curlPath `
  -k `
  -u "$jiraUser`:$jiraPass" `
  "$jiraBaseUrl/rest/api/2/issue/$ISSUE_KEY?fields=attachment" | ConvertFrom-Json

foreach ($att in $issueJson.fields.attachment) {
    Write-Host "Deleting attachment $($att.id) : $($att.filename)"

    Invoke-JiraCurl `
      -Label "Delete attachment $($att.id)" `
      -CurlArgs @(
        '-k',
        '-u', "$jiraUser`:$jiraPass",
        '-X', 'DELETE',
        "$jiraBaseUrl/rest/api/2/attachment/$($att.id)"
      )
}