# Clarification Answers 1

Created: 2026-06-08 08:08:33

## Q001

Question:
What are the password complexity requirements (e.g., must include uppercase, lowercase, digit, special character)?

Answer:
Requirements for password complexityMật khẩu phải từ 8 đến 64 ký tự. Yêu cầu chứa ít nhất một chữ hoa, một chữ thường, một chữ số và một ký tự đặc biệt (ví dụ: @, #, $). Không được chứa khoảng trắng hoặc thông tin cá nhân rõ ràng như tên người dùng.

Impact:
High

---

## Q002

Question:
What is the exact email format validation rule (e.g., RFC 5322, simple regex, or specific domain restrictions)?

Answer:
Email format validation ruleHệ thống sử dụng quy tắc xác thực dựa trên tiêu chuẩn RFC 5322 dạng rút gọn để đảm bảo tính thực tế. Không áp dụng hạn chế đối với các tên miền cụ thể, ngoại trừ việc chặn các nhà cung cấp email tạm thời (disposable email providers) phổ biến.

Impact:
High

---

## Q003

Question:
What error messages should be displayed for duplicate email, invalid password length, and invalid email format?

Answer:
Error messages for registration failuresEmail trùng lặp: "Email này đã được đăng ký. Vui lòng đăng nhập hoặc sử dụng email khác."Độ dài mật khẩu không hợp lệ: "Mật khẩu phải có độ dài từ 8 đến 64 ký tự."Định dạng email không hợp lệ: "Địa chỉ email không đúng định dạng. Vui lòng kiểm tra lại."

Impact:
Medium

---

## Q004

Question:
What is the email verification process (e.g., time limit for verification, resend policy, link expiration)?

Answer:
Email verification processHệ thống sẽ gửi một liên kết xác thực duy nhất qua email ngay sau khi đăng ký. Liên kết này có hiệu lực trong vòng 24 giờ. Người dùng có thể yêu cầu gửi lại mã (resend) sau mỗi 60 giây.

Impact:
High

---

## Q005

Question:
Are there any rate limits or brute-force protection mechanisms for account creation or email verification attempts?

Answer:
Rate limits and brute-force protectionĐăng ký tài khoản: Tối đa 5 lần thử trên một địa chỉ IP trong vòng 15 phút.Yêu cầu gửi lại email xác thực: Tối đa 3 lần thử trên một tài khoản trong vòng 1 giờ. Nếu vượt quá, IP hoặc tài khoản sẽ bị tạm khóa tính năng này trong 30 phút.

Impact:
Medium

---

