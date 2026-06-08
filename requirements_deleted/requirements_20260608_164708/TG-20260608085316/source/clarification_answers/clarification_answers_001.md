# Clarification Answers 1

Created: 2026-06-08 09:01:22

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
What is the exact email format validation rule (e.g., RFC 5322, simple regex, or specific domain restrictions)?

Answer:
Email format must contain @ and domain

Impact:
High

---

## Q003

Question:
What error messages should be displayed for duplicate email, invalid email format, and invalid password length?

Answer:
meaningful inline error

Impact:
Medium

---

## Q004

Question:
What is the email verification mechanism (e.g., time-limited token, link expiration, resend policy)?

Answer:
Hệ thống sẽ gửi một liên kết xác thực duy nhất qua email ngay sau khi đăng ký. Liên kết này có hiệu lực trong vòng 24 giờ. Người dùng có thể yêu cầu gửi lại mã (resend) sau mỗi 60 giây

Impact:
High

---

## Q005

Question:
Are passwords of exactly 8 and exactly 12 characters allowed, and what about leading/trailing spaces?

Answer:
password length from 8 to 12 characters, do not trim leading/trailing spaces

Impact:
Medium

---

