curl --request PUT \
  --header "PRIVATE-TOKEN: glpat-xxxxxxxx" \
  --form "active=true" \
  "https://gitlab.com/api/v4/projects/123456/pipeline_schedules/42"