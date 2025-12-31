# services/email_service.py
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from core import config

logger = logging.getLogger(__name__)


def send_email(subject: str, html_content: str):
    """HTML 형식의 이메일을 발송합니다."""

    # 이메일 설정이 없으면 발송 생략
    if not config.SMTP_EMAIL or not config.SMTP_PASSWORD:
        logger.warning("⚠️ 이메일 설정이 없어 이메일 발송을 건너뜁니다.")
        return False

    try:
        # 이메일 객체 생성
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.SMTP_EMAIL
        msg["To"] = config.SMTP_EMAIL  # 본인에게 발송

        # HTML 본문 추가
        # 텔레그램용 HTML 태그(<br> 등)를 이메일에서도 보기 좋게 스타일링
        styled_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="background-color: #f4f4f4; padding: 20px; border-radius: 10px;">
                    <h2 style="color: #2c3e50;">📅 일정 알림</h2>
                    <div style="background-color: #ffffff; padding: 15px; border-radius: 5px; border-left: 5px solid #007bff;">
                        {html_content.replace(chr(10), '<br>')}
                    </div>
                    <p style="font-size: 0.8em; color: #777; margin-top: 20px;">
                        Synology Telegram Bot에서 발송된 자동 메시지입니다.
                    </p>
                </div>
            </body>
        </html>
        """
        msg.attach(MIMEText(styled_content, "html"))

        # SMTP 서버 연결 및 발송
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
            server.starttls()  # 보안 연결
            server.login(config.SMTP_EMAIL, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_EMAIL, config.SMTP_EMAIL, msg.as_string())

        logger.info(f"📧 이메일 발송 성공: {subject}")
        return True

    except Exception as e:
        logger.error(f"❌ 이메일 발송 실패: {e}")
        return False
