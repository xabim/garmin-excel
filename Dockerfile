FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
# Mount the xlsx dir at /data and a token dir at /tokens:
#   docker run -it --rm -v /path/to/plans:/data:ro -v ~/.config/garmin-excel/tokens:/tokens \
#     -e GARMIN_EXCEL_TOKENS=/tokens garmin-excel preview --input "/data/plan 19_25 oct.xlsx" --week-number 4
ENTRYPOINT ["garmin-excel"]
