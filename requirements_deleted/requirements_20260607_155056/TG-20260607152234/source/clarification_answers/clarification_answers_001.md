# Clarification Answers 1

Created: 2026-06-07 15:25:26

## Q001

Question:
What is the exact email format validation rule (e.g., regex pattern, allowed characters, length limits)?

Answer:
Password length 8 ~ 12 characters, include at least number, special character, alphabet character

Impact:
High

---

## Q002

Question:
What are the password requirements (minimum and maximum length, required character types, allowed special characters, any blacklist)?

Answer:
user must verify email before first login

Impact:
High

---

## Q003

Question:
Is email verification required before the account is considered active or usable? If yes, what is the verification process (e.g., confirmation link, expiration)?

Answer:
meaningful inline error

Impact:
High

---

## Q004

Question:
Is a password confirmation field required during account creation?

Answer:
First name, last name, username, phone number, email, password, confirm password

Impact:
Medium

---

## Q005

Question:
What error messages and HTTP status codes should be returned for duplicate email addresses and invalid inputs (e.g., malformed email, weak password)?

Answer:
meaningful inline error

Impact:
High

---

