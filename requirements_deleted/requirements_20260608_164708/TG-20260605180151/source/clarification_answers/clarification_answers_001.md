# Clarification Answers 1

Created: 2026-06-05 18:03:24

## Q001

Question:
What are the exact password complexity requirements beyond minimum length (e.g., must include uppercase, lowercase, digit, special character)?

Answer:
Password length 8 ~ 12 characters, include at least number, special character, alphabet character

Impact:
High

---

## Q002

Question:
What specific error messages or user feedback should be displayed for validation failures (e.g., duplicate email, short password, invalid email format)?

Answer:
meaningful inline error

Impact:
High

---

## Q003

Question:
Is email verification required before the account is considered active, and if so, what is the verification mechanism (e.g., confirmation link, OTP)?

Answer:
User must verify email before first login

Impact:
High

---

## Q004

Question:
How and where is user account data stored (e.g., database type, encryption of passwords, data retention policy)?

Answer:
database

Impact:
High

---

## Q005

Question:
What is the maximum length for email and password fields, and how should the system handle leading/trailing whitespace in email or password inputs?

Answer:
email max length = 255, password max length = 12

Impact:
Medium

---

