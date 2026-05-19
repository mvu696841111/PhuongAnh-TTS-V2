import bcrypt

hashed = b"$2b$12$FraJuU1.ZeGhLkVk9NSWL.0o8W0yIRJxTWh5U2iNM1Q5PpXM8eilO"

password = b"123456"

if bcrypt.checkpw(password, hashed):
    print("Dung mat khau")
else:
    print("Sai")