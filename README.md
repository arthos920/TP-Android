$commentText = @'
📎 Robot Framework results available

Pipeline:
__PIPELINE_URL__

Artifacts:
__PIPELINE_URL__/artifacts/browse/results/

Main files:
- report.html
- log.html
- output.xml
- results.zip
'@

$commentText = $commentText -replace '__PIPELINE_URL__', $CI_PIPELINE_URL

$commentBody = @{
    body = $commentText
} | ConvertTo-Json -Depth 5