"""
洛谷验证码处理模块

功能：
1. 获取验证码图片
2. 使用ddddocr自动识别
3. 提供手动输入接口（用于QQ群聊交互）
"""

import base64
import io
from typing import Optional, Tuple
from PIL import Image

class CaptchaHandler:
    """验证码处理类"""
    
    def __init__(self, use_auto_ocr: bool = True):
        """
        初始化验证码处理器
        
        Args:
            use_auto_ocr: 是否自动使用OCR识别
        """
        self.use_auto_ocr = use_auto_ocr
        self.ocr = None
        
        if self.use_auto_ocr:
            self._init_ocr()
    
    def _init_ocr(self):
        """初始化OCR识别器"""
        try:
            import ddddocr
            self.ocr = ddddocr.DdddOcr(show_ad=False)
            print("ddddocr初始化成功")
        except ImportError:
            print("ddddocr未安装，验证码自动识别功能不可用")
            print("请运行: pip install ddddocr")
            self.ocr = None
        except Exception as e:
            print(f"ddddocr初始化失败: {e}")
            self.ocr = None
    
    def recognize(self, image_data: bytes) -> str:
        """
        识别验证码
        
        Args:
            image_data: 验证码图片字节数据
        
        Returns:
            识别出的验证码文本
        """
        if self.ocr:
            try:
                result = self.ocr.classification(image_data)
                return result
            except Exception as e:
                print(f"验证码识别失败: {e}")
                return ""
        else:
            return ""
    
    def recognize_from_base64(self, base64_str: str) -> str:
        """
        从base64字符串识别验证码
        
        Args:
            base64_str: base64编码的图片字符串
        
        Returns:
            识别出的验证码文本
        """
        try:
            image_data = base64.b64decode(base64_str)
            return self.recognize(image_data)
        except Exception as e:
            print(f"Base64解码失败: {e}")
            return ""
    
    def recognize_from_file(self, filepath: str) -> str:
        """
        从文件识别验证码
        
        Args:
            filepath: 图片文件路径
        
        Returns:
            识别出的验证码文本
        """
        try:
            with open(filepath, "rb") as f:
                image_data = f.read()
            return self.recognize(image_data)
        except Exception as e:
            print(f"文件读取失败: {e}")
            return ""
    
    def get_captcha_image(self, session, captcha_url: str) -> Optional[bytes]:
        """
        从洛谷获取验证码图片
        
        Args:
            session: requests会话
            captcha_url: 验证码URL
        
        Returns:
            验证码图片字节数据
        """
        try:
            response = session.get(captcha_url)
            if response.status_code == 200:
                return response.content
        except Exception as e:
            print(f"获取验证码失败: {e}")
        return None
    
    def save_captcha_image(self, image_data: bytes, filepath: str = "captcha.png"):
        """
        保存验证码图片（用于调试或手动识别）
        
        Args:
            image_data: 图片字节数据
            filepath: 保存路径
        """
        try:
            with open(filepath, "wb") as f:
                f.write(image_data)
            print(f"验证码图片已保存: {filepath}")
        except Exception as e:
            print(f"保存验证码图片失败: {e}")
    
    def preview_captcha(self, image_data: bytes):
        """
        预览验证码图片（需要GUI环境）
        
        Args:
            image_data: 图片字节数据
        """
        try:
            img = Image.open(io.BytesIO(image_data))
            img.show()
        except Exception as e:
            print(f"预览验证码失败: {e}")


# 全局实例
_handler = None

def get_captcha_handler(use_auto_ocr: bool = True) -> CaptchaHandler:
    """获取验证码处理器实例"""
    global _handler
    if _handler is None:
        _handler = CaptchaHandler(use_auto_ocr)
    return _handler
