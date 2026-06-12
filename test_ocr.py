from app.services.LOCAL_image_extractor_service import extract_image_with_LOCAL

image_path = r"F:\AI\qa-ai-platform\sample_requirement.png"

text = extract_image_with_LOCAL(image_path)

print(text)