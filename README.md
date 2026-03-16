def _get_driver(self, driver_name):

    if driver_name == "chrome":
        try:
            ()
        except:
            print("In the good directory")

        path = os.path.abspath("chromedriver.exe")
        print(path)

        service = Service(executable_path=path)

        options = webdriver.ChromeOptions()
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--ignore-ssl-errors')
        options.add_argument('--allow-running-insecure-content')
        options.accept_insecure_certs = True

        self.driver = webdriver.Chrome(service=service, options=options)
        return self.driver

    if driver_name == "firefox":
        options = webdriver.FirefoxOptions()
        options.accept_insecure_certs = True

        self.driver = webdriver.Firefox(options=options)
        return self.driver