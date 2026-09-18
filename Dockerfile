# One image for every script. They share three dependencies and differ only in
# which module runs, so building seven images would mean seven copies of pandas.
FROM python:3.12-slim

# pillow needs zlib and libjpeg at runtime to write the downscaled PNG and JPEG.
# slim carries neither, and the failure is a confusing "encoder not available"
# deep inside the build rather than an install error.
RUN apt-get update \
 && apt-get install -y --no-install-recommends zlib1g libjpeg62-turbo \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

# Copied alone so the layer caches: editing a script does not reinstall pandas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The repository is bind-mounted over /repo at run time, so nothing else is
# copied in. Outputs land on the host where the next service, and git, can see
# them.

# Unbuffered, or the logs of a long build arrive in a lump at the end.
ENV PYTHONUNBUFFERED=1

CMD ["python", "--version"]
