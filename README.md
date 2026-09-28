.check_actors_template:
  timeout: 1h15m

  variables:
    RUNNER_SCRIPT_TIMEOUT: "1h"
    RUNNER_AFTER_SCRIPT_TIMEOUT: "10m"

  before_script:
    - git config --global http.sslBackend openssl
    - git config --global http.sslVerify false

  script:
    - pwd
    - ls ./scripts
    - $env:ROBOT_OUTPUT_DIR = "results"
    - >-
      powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass
      -File "./scripts/check_actors_launch.ps1"
      -LAB "$env:LAB"
      -URL "$env:CI_PIPELINE_URL"
      -EMAIL "$env:EMAIL"
      -ISSUE_KEY "$env:ISSUE_KEY"

  after_script:
    - >-
      powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass
      -File "./scripts/check_actors_launch.ps1"
      -LAB "$env:LAB"
      -URL "$env:CI_PIPELINE_URL"
      -EMAIL "$env:EMAIL"
      -ISSUE_KEY "$env:ISSUE_KEY"
      -AfterJob

  artifacts:
    when: always
    paths:
      - results/

  allow_failure: false