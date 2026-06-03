import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from core import config

logger = logging.getLogger(__name__)

def send_email(subject: str, body: str) -> bool:
    """SMTP를 사용하여 이메일을 발송하는 함수"""
    # 설정이 누락되었다면 에러를 내지 않고 조용히 취소 (봇 다운 방지)
    if not config.SMTP_EMAIL or not config.SMTP_PASSWORD:
        logger.debug("⚠️ SMTP 설정이 누락되어 이메일 발송을 건너뜁니다.")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = config.SMTP_EMAIL
        msg['To'] = config.SMTP_EMAIL  # 봇이 나에게 보내는 것이므로 동일하게 설정
        msg['Subject'] = subject

        # 텔레그램용 줄바꿈(\n)을 이메일 HTML 태그(<br>)로 변환
        html_body = body.replace('\n', '<br>')
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config.SMTP_EMAIL, config.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"📧 이메일 발송 성공: {subject}")
        return True

    except Exception as e:
        logger.error(f"❌ 이메일 발송 실패: {e}")
        return False
