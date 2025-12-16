variables:
  # Proxy obligatoire pour Git / GitLab
  HTTP_PROXY: ""
  HTTPS_PROXY: ""

  # Bypass proxy pour Appium / localhost
  NO_PROXY: "localhost,127.0.0.1"
  no_proxy: "localhost,127.0.0.1"

  # SSL Git (environnement corporate)
  GIT_SSL_NO_VERIFY: "true"

  SHELL: powershell

# ============================================================
# TEMPLATE : CHECK ACTORS
# ============================================================
.check_actors_template:
  before_script:
    - git config --global http.sslVerify false

  script:
    - pwd
    - ls ./scripts
    - powershell -ExecutionPolicy Bypass -File "./scripts/check_actors_launch.ps1" `
        -LAB $env:LAB `
        -URL $CI_PIPELINE_URL `
        -EMAIL $env:EMAIL `
        -ISSUE_KEY $env:ISSUE_KEY

  artifacts:
    when: always
    paths:
      - output.txt
      - log_actors.html
      - report_actors.html
      - check_actors.xml

  allow_failure: false

# ============================================================
# TEMPLATE : FETCH TEST CASES
# ============================================================
.fetch_tests_cases_template:
  before_script:
    - git config --global http.sslVerify false

  script:
    - ls ./scripts
    - echo "The CI URL is $CI_PIPELINE_URL"
    - powershell -ExecutionPolicy Bypass -File "./scripts/fetch_tests.ps1" `
        -ISSUE_KEY $env:ISSUE_KEY `
        -LAB $env:LAB `
        -URL $CI_PIPELINE_URL `
        -EMAIL $env:EMAIL

  artifacts:
    when: always
    paths:
      - output.txt
      - log.html
      - report.html
      - check.xml

# ============================================================
# JOBS PAR LAB
# ============================================================

check_actors_SolutionSYS03:
  extends: .check_actors_template
  tags:
    - PC-VIRT804
  rules:
    - if: '$LAB == "SolutionSYS03"'

fetch_tests_SolutionSYS03:
  extends: .fetch_tests_cases_template
  tags:
    - PC-VIRT804
  rules:
    - if: '$LAB == "SolutionSYS03"'
