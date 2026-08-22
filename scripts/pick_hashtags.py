import random

with open("hashtags.txt", encoding="utf-8") as f:
    lines = [l.strip() for l in f if l.strip()]

count = min(6, len(lines))
print(" ".join(random.sample(lines, count)))
