# Clarification Answers 1

Created: 2026-06-08 08:35:20

## Q001

Question:
What error message or behavior should occur when email verification fails (e.g., link expired, invalid token, or system error)?

Answer:
Link expired / Invalid token: The system displays the message: "The verification link is invalid or has expired. Please request a new one." The user is redirected to a page where they can trigger a new verification email.System error: The system displays: "An unexpected error occurred. Please try again later."Security behavior: In all failure cases, the raw database or system error details are hidden from the frontend to prevent information disclosure.

Impact:
High

---

## Q002

Question:
Is there a time limit for email verification (e.g., 24 hours), and what happens if the user tries to verify after the limit expires?

Answer:
Time limit: The email verification link expires exactly 24 hours after issuance.Expired behavior: If clicked after 24 hours, the link is treated as invalid. The system shows an expiration message and provides a "Resend Verification Email" button on the landing page. The unverified user record remains in the database for up to 7 days before being automatically purged.

Impact:
High

---

## Q003

Question:
What are the password complexity requirements beyond length (e.g., must include uppercase, lowercase, digit, special character)?

Answer:
Character types: The password must contain at least one uppercase letter, one lowercase letter, one numeric digit, and one special character (e.g., @, #, $, %, ^, &, *).Restrictions: Consecutive spaces are forbidden. The password cannot contain the user's explicit email prefix or username to mitigate easy guessing.

Impact:
High

---

## Q004

Question:
How is the email verification sent (e.g., link with token, one-time code), and what are the security measures to prevent token reuse or interception?

Answer:
Delivery method: The system sends a secure URL containing a cryptographically secure, high-entropy random token as a query parameter.Security measures: Tokens are single-use only. Once clicked or validated, the token is immediately invalidated in the database. Tokens are hashed (using SHA-256) before storage in the database to prevent interception risks if the database is compromised. All verification traffic is strictly enforced over HTTPS (TLS 1.3).

Impact:
High

---

## Q005

Question:
What happens if a user attempts to create an account with an email that already exists but is not yet verified?

Answer:
Behavior: The system allows the registration flow to proceed normally from the frontend perspective to prevent email enumeration attacks.Backend logic: Instead of creating a duplicate row, the system updates the existing unverified record with the new password hash and generates a brand-new verification token, sending it to the email address. This resets the 24-hour expiration clock.

Impact:
Medium

---

