"""Helper utility to display the current 6-digit TOTP for owner@dayjournal.app"""
import pyotp

TOTP_SECRET = "XTFCPO6CBAXSKWERR7L2D3UYQOVMGBRD"

def main():
    totp = pyotp.TOTP(TOTP_SECRET)
    print("=" * 50)
    print("ACTIVE ADMIN TOTP CREDENTIALS")
    print("=" * 50)
    print(f"Account:      owner@dayjournal.app")
    print(f"Current Code: {totp.now()}")
    print(f"Secret:       {TOTP_SECRET}")
    print("=" * 50)

if __name__ == "__main__":
    main()
