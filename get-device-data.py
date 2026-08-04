from libdyson.cloud import DysonAccount
from getpass import getpass

email = "rawestmoreland@gmail.com"
country = "CH"

account = DysonAccount()
verify = account.login_email_otp(email, country)

print(f"Check your email ({email}) for a one-time password.")
otp = input("Enter OTP: ")
password = getpass("Dyson account password: ")

verify(otp, password)  # this completes the login

devices = account.devices()
for d in devices:
    print(d.name, d.serial, d.product_type)
