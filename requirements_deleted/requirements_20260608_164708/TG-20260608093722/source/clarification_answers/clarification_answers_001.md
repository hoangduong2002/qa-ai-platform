# Clarification Answers 1

Created: 2026-06-08 09:39:36

## Q001

Question:
What are the password complexity requirements (e.g., must include uppercase, lowercase, digit, special character)?

Answer:
Character types: The password must contain at least one uppercase letter, one lowercase letter, one numeric digit, and one special character (e.g., @, #, $, %, ^, &, *). Restrictions: Consecutive spaces are forbidden. The password cannot contain the user's explicit email prefix or username to mitigate easy guessing.

Impact:
High

---

## Q002

Question:
What is the exact email format validation rule (e.g., must contain '@' and a domain, allowed characters)?

Answer:
Email format must contain @ and domain

Impact:
High

---

## Q003

Question:
What error messages should be displayed for duplicate email, invalid password length, or invalid email format?

Answer:
meaningful inline error

Impact:
Medium

---

## Q004

Question:
What is the email verification method (e.g., clickable link, one-time code) and what is the expiration time for the verification token?

Answer:
The system will send a unique verification link via email immediately after registration. This link is valid for 24 hours. Users can request a resend of the code every 60 seconds.

Impact:
High

---

## Q005

Question:
What additional fields (e.g., name, phone) are required during account creation, and what are their validation rules?

Answer:
First name, Last name, email, phone, password, confirm password

Impact:
Medium

---

