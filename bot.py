import logging
import re
import html
import os
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ==================== LOGGING ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DECODER ENGINE ====================
class RDXDecoder:
    @staticmethod
    def decode_css_content(content_str: str) -> str:
        """Decode CSS content with Unicode escape sequences"""
        cleaned = content_str.strip().strip("'\"")
        matches = re.findall(r'\\+[0-9a-fA-F]+', cleaned)
        if not matches:
            return cleaned
        result = []
        for match in matches:
            hex_part = re.sub(r'^\\+', '', match)
            try:
                result.append(chr(int(hex_part, 16)))
            except (ValueError, OverflowError):
                result.append("")
        return ''.join(result)
    
    @staticmethod
    def decrypt_script_block(script_text: str) -> str:
        """Simulate script execution to extract decrypted content"""
        collected = []
        
        def fake_eval(code):
            collected.append(code)
        
        class MockObject:
            def __getattr__(self, name):
                return self
            def __call__(self, *args, **kwargs):
                return self
            def __getitem__(self, key):
                return self
        
        mock = MockObject()
        
        try:
            sandbox = {
                'window': mock,
                'document': mock,
                'eval': fake_eval,
                'self': mock,
                'top': mock,
                'parent': mock,
                'globalThis': mock,
                'navigator': mock,
                'location': mock,
                'console': mock,
                'setTimeout': lambda *args: None,
                'setInterval': lambda *args: None,
                'clearTimeout': lambda *args: None,
                'clearInterval': lambda *args: None,
            }
            
            exec_globals = {
                '__builtins__': {
                    'len': len,
                    'str': str,
                    'int': int,
                    'float': float,
                    'bool': bool,
                    'list': list,
                    'dict': dict,
                    'tuple': tuple,
                    'range': range,
                    'zip': zip,
                    'map': map,
                    'filter': filter,
                    'any': any,
                    'all': all,
                    'sum': sum,
                    'min': min,
                    'max': max,
                    'abs': abs,
                    'round': round,
                    'ord': ord,
                    'chr': chr,
                    'hex': hex,
                    'oct': oct,
                    'bin': bin,
                    'isinstance': isinstance,
                    'type': type,
                    'print': lambda *args: None,
                }
            }
            
            exec_globals.update(sandbox)
            exec(script_text, exec_globals)
            
        except Exception as e:
            logger.debug(f"Script execution error: {e}")
            pass
        
        return '\n'.join(collected)
    
    @classmethod
    def decode_html(cls, html_content: str) -> str:
        """Main decoding function"""
        # 1) Extract s-eto rules from <style>
        rule_map = {}
        style_regex = re.compile(r'<style[^>]*>([\s\S]*?)<\/style>', re.IGNORECASE)
        style_block_to_remove = None
        
        for style_match in style_regex.finditer(html_content):
            style_content = style_match.group(1)
            if 's-eto' in style_content:
                style_block_to_remove = style_match.group(0)
                rule_regex = re.compile(
                    r'#([a-zA-Z0-9_-]+):+:before\s*\{\s*content\s*:\s*([^;}]+)\s*;?\s*\}',
                    re.IGNORECASE
                )
                for rule_match in rule_regex.finditer(style_content):
                    element_id = rule_match.group(1)
                    content_value = rule_match.group(2)
                    rule_map[element_id] = cls.decode_css_content(content_value)
        
        # 2) Parse HTML using html5lib (works on Render)
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html5lib')
        except ImportError:
            # Fallback: use regex-based decoding
            soup = None
        
        if soup:
            # 3) Replace <s-eto> elements with text nodes
            for s_eto in soup.find_all('s-eto'):
                element_id = s_eto.get('id')
                if element_id and element_id in rule_map:
                    s_eto.replace_with(rule_map[element_id])
            
            # 4) Remove style containing s-eto
            if style_block_to_remove:
                for style_tag in soup.find_all('style'):
                    if style_tag.string and 's-eto' in style_tag.string:
                        style_tag.decompose()
            
            # 5) Handle script decryption
            for script_tag in soup.find_all('script'):
                script_text = script_tag.string or ''
                if (
                    'eval' in script_text and (
                        '_xaMzEdGx' in script_text or
                        '_o9MZPdaJ' in script_text or
                        '_ayVZcO8Eg' in script_text or
                        '_csdsUKQwG' in script_text or
                        "window['_" in script_text or
                        re.search(r'var\s+_[a-zA-Z0-9]{8,15}\s*=\s*\[\s*\d+', script_text)
                    )
                ):
                    decrypted = cls.decrypt_script_block(script_text)
                    if decrypted and decrypted.strip():
                        script_tag.string = '\n' + decrypted.strip() + '\n'
            
            # 6) Rebuild HTML
            output = str(soup)
        else:
            # Fallback: use regex-based decoding
            output = html_content
            # Simple replacements
            for elem_id, content in rule_map.items():
                output = re.sub(
                    rf'<s-eto\s+id=["\']?{elem_id}["\']?>\s*</s-eto>',
                    content,
                    output
                )
            
            # Remove style blocks with s-eto
            if style_block_to_remove:
                output = output.replace(style_block_to_remove, '')
        
        # 7) Strip obfuscator comment banner
        banner_regex = re.compile(
            r'<!--\s*╔══════════════════════════════════════════════════════════╗[\s\S]*?╚══════════════════════════════════════════════════════════╝\s*-->',
            re.IGNORECASE
        )
        output = banner_regex.sub('', output)
        
        # 8) Ensure DOCTYPE
        if not output.strip().startswith('<!DOCTYPE'):
            output = '<!DOCTYPE html>\n' + output
        
        return output


# ==================== BOT HANDLERS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    welcome_text = (
        f"🚀 <b>RDX DECODER PRO</b>\n\n"
        f"Welcome, {user.mention_html()}!\n\n"
        f"<b>What I can do:</b>\n"
        f"🔓 Deobfuscate HTML code\n"
        f"🧹 Clean obfuscated JavaScript\n"
        f"📄 Recover original source code\n\n"
        f"<b>How to use:</b>\n"
        f"1️⃣ Send me an obfuscated .html file\n"
        f"2️⃣ Or paste the HTML code directly\n"
        f"3️⃣ I'll decode and return the clean version\n\n"
        f"<i>Powered by RDX Secure · Enterprise v4.2.0</i>"
    )
    
    keyboard = [
        [InlineKeyboardButton("📤 Send File", callback_data="send_file")],
        [InlineKeyboardButton("📋 How to Use", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "📖 <b>RDX Decoder - User Guide</b>\n\n"
        "<b>Supported Input:</b>\n"
        "• Obfuscated HTML files (.html, .htm)\n"
        "• Direct HTML code paste\n"
        "• Drag & drop (via Telegram Web/Desktop)\n\n"
        "<b>What gets decoded:</b>\n"
        "• CSS Unicode escapes (\\xxxx)\n"
        "• s-eto element replacements\n"
        "• Eval-based script obfuscation\n"
        "• Custom obfuscator patterns\n\n"
        "<b>Features:</b>\n"
        "✅ Automatic detection\n"
        "✅ Clean output with DOCTYPE\n"
        "✅ Removes obfuscator banners\n"
        "✅ Preserves HTML structure\n\n"
        "<b>Limitations:</b>\n"
        "• File size: max 10MB\n"
        "• Complex JS may need manual review\n"
        "• Some obfuscators may resist decoding"
    )
    
    await update.message.reply_text(help_text, parse_mode='HTML')


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded document files"""
    document = update.message.document
    
    # Check file type
    if not document.file_name or not document.file_name.endswith(('.html', '.htm')):
        await update.message.reply_text(
            "❌ Please send an HTML file (.html or .htm extension)"
        )
        return
    
    # Check file size (10MB limit)
    if document.file_size > 10 * 1024 * 1024:
        await update.message.reply_text(
            "❌ File too large! Maximum size is 10MB."
        )
        return
    
    processing_msg = await update.message.reply_text(
        "🔄 Processing your file... Please wait."
    )
    
    try:
        # Download file
        file = await document.get_file()
        file_content = await file.download_as_bytearray()
        html_content = file_content.decode('utf-8', errors='ignore')
        
        # Decode
        decoded = RDXDecoder.decode_html(html_content)
        
        # Create download file
        output_bytes = decoded.encode('utf-8')
        output_file = BytesIO(output_bytes)
        output_file.name = f"decoded_{document.file_name}"
        
        # Send back decoded file
        await update.message.reply_document(
            document=output_file,
            filename=f"RDX_decoded_{document.file_name}",
            caption=f"✅ Successfully decoded!\n\n📊 Original size: {len(html_content):,} chars\n🧹 Clean size: {len(decoded):,} chars"
        )
        
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        await processing_msg.edit_text(
            f"❌ Error processing file: {str(e)[:100]}\n\nPlease try again or contact support."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input (HTML code)"""
    text = update.message.text
    
    # Check if it looks like HTML
    if not any(tag in text.lower() for tag in ['<html', '<body', '<head', '<script', '<div', '<style']):
        await update.message.reply_text(
            "ℹ️ This doesn't look like HTML code.\n\n"
            "Send me an HTML file or paste valid HTML code to decode."
        )
        return
    
    processing_msg = await update.message.reply_text(
        "🔄 Decoding HTML code... Please wait."
    )
    
    try:
        # Decode
        decoded = RDXDecoder.decode_html(text)
        
        # Check if decoded content is too long for message
        if len(decoded) > 4000:
            # Send as file
            output_bytes = decoded.encode('utf-8')
            output_file = BytesIO(output_bytes)
            output_file.name = "decoded_output.html"
            
            await update.message.reply_document(
                document=output_file,
                filename="RDX_decoded_code.html",
                caption="✅ Decoding complete! Output is large, sent as file."
            )
        else:
            # Send as text
            await update.message.reply_text(
                f"✅ <b>Decoded HTML</b>\n\n<pre>{html.escape(decoded)}</pre>",
                parse_mode='HTML'
            )
        
        await processing_msg.delete()
        
    except Exception as e:
        logger.error(f"Error decoding text: {e}")
        await processing_msg.edit_text(
            f"❌ Error decoding: {str(e)[:100]}\n\nPlease check the input format."
        )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "send_file":
        await query.edit_message_text(
            "📤 <b>Send me your file</b>\n\n"
            "Click the attachment icon (📎) and select your .html file.\n\n"
            "I'll decode it and send back the clean version.",
            parse_mode='HTML'
        )
    
    elif query.data == "help":
        help_text = (
            "📖 <b>Quick Help</b>\n\n"
            "1️⃣ <b>Upload file:</b> Send as document\n"
            "2️⃣ <b>Paste code:</b> Send as text message\n"
            "3️⃣ <b>Drag & drop:</b> Works in Telegram Desktop\n\n"
            "I'll automatically detect and decode obfuscated code.\n\n"
            "⚡ <b>Pro tip:</b> Send large files as documents for best results."
        )
        await query.edit_message_text(help_text, parse_mode='HTML')


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ An unexpected error occurred. Please try again later."
            )
    except Exception:
        pass


# ==================== MAIN ====================

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Document handler - for file uploads
    application.add_handler(MessageHandler(
        filters.Document.ALL,
        handle_document
    ))
    
    # Text handler - for pasted code
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text
    ))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    print("🚀 RDX Decoder Bot is running on Render...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
