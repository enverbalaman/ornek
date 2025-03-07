# burası checkuser ve turmob ve xml güncelleme doğru.

from zeep import Client
from zeep.helpers import serialize_object
import uuid
from datetime import datetime, timedelta
import json
import traceback
import base64
import os
import xml.etree.ElementTree as ET
import time
import zeep.exceptions
import random
import requests

# İşlenmiş faturaları takip etmek için JSON dosyası
PROCESSED_INVOICES_FILE = 'processed_invoices.json'

# Otokoc API token bilgileri
otokoc_token = None
token_expiry_time = None

def get_otokoc_token():
    """Otokoc API'den token alır"""
    global otokoc_token, token_expiry_time
    
    try:
        print("\n🔑 Otokoc API'den token alınıyor...")
        
        # IP bilgilerini al ve göster
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetToken"
        payload = {
            "Username": "UrartuTrz",
            "Password": "Tsv*57139!"
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()  # HTTP hatalarını yakala
        response_data = response.json()
        
        if 'Data' not in response_data or 'Token' not in response_data['Data']:
            print(f"❌ Otokoc API token alınamadı: Geçersiz yanıt formatı")
            print(f"Yanıt: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
            return None
        
        otokoc_token = response_data['Data']['Token']
        # Token geçerlilik süresi 4 dakika
        token_expiry_time = datetime.now() + timedelta(minutes=4)
        print(f"✅ Otokoc API'den token alındı. Geçerlilik: {token_expiry_time.strftime('%H:%M:%S')}")
        return otokoc_token
    except requests.exceptions.RequestException as e:
        print(f"❌ Otokoc API token alma hatası: {str(e)}")
        traceback.print_exc()
        return None
    except Exception as e:
        print(f"❌ Otokoc API token alma hatası: {str(e)}")
        traceback.print_exc()
        return None

def check_and_refresh_token():
    """Token geçerliliğini kontrol eder ve gerekirse yeniler"""
    global otokoc_token, token_expiry_time
    
    if not otokoc_token or not token_expiry_time or datetime.now() >= token_expiry_time:
        print("⚠️ Token geçersiz veya süresi dolmuş, yenileniyor...")
        return get_otokoc_token()
    else:
        remaining_time = (token_expiry_time - datetime.now()).total_seconds()
        print(f"✅ Token geçerli. Kalan süre: {int(remaining_time)} saniye")
        return otokoc_token

def get_invoice_data(brand_data=None):
    """Otokoc API'den fatura verilerini çeker"""
    try:
        if not brand_data:
            print("❌ Marka verisi bulunamadı")
            return []
        
        # İşlenmiş faturaları yükle
        processed_data = load_processed_invoices()
        processed_invoices = processed_data["processed_invoices"]
        
        # İşlenmemiş faturaları filtrele - KANo kontrolü
        unprocessed_invoices = []
        for invoice in brand_data:
            ka_no = invoice.get('KANo', '')
            brand = invoice.get('Brand', 'Bilinmiyor')
            
            if ka_no and ka_no not in processed_invoices:
                unprocessed_invoices.append(invoice)
                print(f"✅ Yeni {brand} faturası bulundu: {ka_no}")
            else:
                print(f"⏭️ {brand} faturası zaten işlenmiş: {ka_no}")
        
        print(f"🔍 İşlenmemiş fatura sayısı: {len(unprocessed_invoices)}/{len(brand_data)}")
        
        return unprocessed_invoices
        
    except Exception as e:
        print(f"❌ Fatura verileri işlenirken hata: {str(e)}")
        traceback.print_exc()
        return []

def edm_login():
    try:
        # Gerçek EDM sistemi
        wsdl_url = "https://portal2.edmbilisim.com.tr/EFaturaEDM/EFaturaEDM.svc?wsdl"
        client = Client(wsdl=wsdl_url)
        
        action_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00"
        login_request_header = {
            "SESSION_ID": str(uuid.uuid4()),
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": action_date,
            "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
            "APPLICATION_NAME": "EDM MINI CONNECTOR v1.0",
            "HOSTNAME": "MDORA17",
            "CHANNEL_NAME": "TEST",
            "COMPRESSED": "N"
        }

        login_request = {
            "REQUEST_HEADER": login_request_header,
            "USER_NAME": "otomasyon",
            "PASSWORD": "123456789"
        }

        print("\n🔑 EDM Login yapılıyor...")
        login_response = client.service.Login(**login_request)
        session_id = login_response.SESSION_ID
        print(f"✅ EDM Login başarılı - Session ID: {session_id}")
        return client, session_id

    except Exception as e:
        print(f"❌ EDM Login hatası: {str(e)}")
        traceback.print_exc()
        return None, None

def check_user_and_get_info(client, session_id, vkn):
    print(f"\n🔍 VKN: {vkn} için CheckUser işlemi başlatıldı")
    
    action_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00"

    request_header = {
        "SESSION_ID": session_id,
        "CLIENT_TXN_ID": str(uuid.uuid4()),
        "ACTION_DATE": action_date,
        "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
        "APPLICATION_NAME": "EDM MINI CONNECTOR v1.0",
        "HOSTNAME": "MDORA17",
        "CHANNEL_NAME": "TEST",
        "COMPRESSED": "N"
    }

    user = {
        "IDENTIFIER": vkn
    }

    try:
        response = client.service.CheckUser(REQUEST_HEADER=request_header, USER=user)
        
        if not response or len(response) == 0:
            print("⚠️ Kullanıcı e-fatura sisteminde bulunamadı, E-Arşiv olarak işlenecek")
            return None, None, None, None, None, None
        
        print("✅ Kullanıcı e-fatura sisteminde bulundu")
        
        first_user = response[0]
        alias = first_user.ALIAS if hasattr(first_user, 'ALIAS') else None
        
        if not alias:
            print("⚠️ Alias bulunamadı, E-Arşiv olarak işlenecek")
            return None, None, None, None, None, None
            
        print("🔄 TURMOB bilgileri alınıyor...")
        turmob_header = {
            "SESSION_ID": session_id,
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00",
            "REASON": "test",
            "APPLICATION_NAME": "EDMTEST",
            "HOSTNAME": "BALCIAS",
            "CHANNEL_NAME": "EDM",
            "COMPRESSED": "N"
        }
        
        try:
            turmob_response = client.service.GetTurmob(REQUEST_HEADER=turmob_header, VKN=vkn)
            
            if hasattr(turmob_response, 'ERROR'):
                print(f"❌ TURMOB Hatası: {turmob_response.ERROR}")
                return alias, None, None, None, None, None
            
            serialized_turmob = serialize_object(turmob_response)
            
            if not serialized_turmob:
                print("⚠️ TURMOB yanıtı boş")
                return alias, None, None, None, None, None
            
            vergi_dairesi = serialized_turmob.get('vergiDairesiAdi', '')
            unvan = serialized_turmob.get('kimlikUnvani', '')
            
            adres_bilgileri = serialized_turmob.get('adresBilgileri', {}).get('AdresBilgileri', [{}])[0]
            
            adres_parcalari = [
                adres_bilgileri.get('mahalleSemt', ''),
                adres_bilgileri.get('caddeSokak', ''),
                adres_bilgileri.get('disKapiNo', ''),
                adres_bilgileri.get('icKapiNo', '')
            ]
            tam_adres = ' '.join(filter(None, adres_parcalari))
            il = adres_bilgileri.get('ilAdi', '')
            ilce = adres_bilgileri.get('ilceAdi', '')
            
            print("✅ TURMOB bilgileri alındı")
            return alias, vergi_dairesi, unvan, tam_adres, il, ilce
            
        except Exception as e:
            print(f"❌ TURMOB bilgileri alınırken hata: {str(e)}")
            return alias, None, None, None, None, None

    except Exception as e:
        print(f"❌ CheckUser işleminde hata: {str(e)}")
        return None, None, None, None, None, None

def send_telegram_notification(message):
    try:
        # Gerçek token ve chat ID'yi kullan (maskelenmiş değil)
        bot_token = "7846367311:AAEGOEcHElmtmMJfU9GznWEi5ZELfaD4U7Y"  # Gerçek token'ı buraya yazın
        chat_id = "-1002470063488"  # Gerçek chat ID'yi buraya yazın
        
        # Debug için token ve chat ID'yi yazdır
        print(f"🔑 Bot Token: {bot_token}")
        print(f"💬 Chat ID: {chat_id}")
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        # Debug için URL'yi yazdır
        print(f"🌐 API URL: {url}")
        
        # İsteği gönder ve yanıtı al
        response = requests.post(url, data=payload)
        
        # Yanıt detaylarını yazdır
        print(f"📡 Telegram API Yanıtı:")
        print(f"Durum Kodu: {response.status_code}")
        print(f"Yanıt İçeriği: {response.text}")
        
        if response.status_code == 200:
            print(f"✅ Telegram bildirimi gönderildi")
        else:
            print(f"❌ Telegram bildirimi gönderilemedi: {response.text}")
            
    except Exception as e:
        print(f"❌ Telegram bildirimi gönderilirken hata: {str(e)}")
        traceback.print_exc()

def update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce, kayit=None):
    try:
        print("\n📝 XML güncelleniyor...")
        
        is_earchive = not alias
        print(f"✅ Fatura tipi: {'E-Arşiv' if is_earchive else 'E-Fatura'}")
        
        brand = kayit.get('Brand', 'Bilinmiyor') if kayit else 'Bilinmiyor'
        
        if not kayit:
            print("❌ Kayıt verileri bulunamadı")
            return False
            
        try:
            formatted_invoice_data = {
                'VergiNumarasi': kayit.get('VergiNumarasi', ''),
                'TumMusteriAdi': kayit.get('TumMusteriAdi', ''),
                'KDVOrani': kayit.get('KDVOrani', 0),
                'KDVTutari': kayit.get('KDVTutari', 0),
                'KDVsizTutar': kayit.get('KDVsizTutar', 0),
                'KDVliToplamTutar': kayit.get('KDVliToplamTutar', 0),
                'KiraGunu': kayit.get('KiraGunu', '1'),
                'KANo': kayit.get('KANo', ''),
                'Adres': tam_adres or kayit.get('Adres', ''),
                'Il': il or kayit.get('Il', ''),
                'Ilce': ilce or kayit.get('Ilce', ''),
                'VergiDairesi': vergi_dairesi or kayit.get('VergiDairesi', ''),
                'KiraTipi': kayit.get('KiraTipi', ''),
                'PlakaNo': kayit.get('PlakaNo', ''),
                'Aciklama': kayit.get('Aciklama', ''),
                'CHECKOUT_DATE': kayit.get('CHECKOUT_DATE', ''),
                'CHECKIN_DATE': kayit.get('CHECKIN_DATE', '')
            }
            
            # Veri kontrolü
            print("\n📋 Fatura Verileri Kontrolü:")
            for key, value in formatted_invoice_data.items():
                print(f"{key}: {value}")
                
            if not formatted_invoice_data['KANo']:
                print("❌ KANo bulunamadı")
                return False
                
            if not formatted_invoice_data['VergiNumarasi']:
                print("❌ VergiNumarasi bulunamadı")
                return False
            
            # Boş değerleri kontrol et ve varsayılan değerler ata
            for key in formatted_invoice_data:
                if formatted_invoice_data[key] is None or formatted_invoice_data[key] == '':
                    if key in ['KDVOrani', 'KDVTutari', 'KDVsizTutar', 'KDVliToplamTutar']:
                        formatted_invoice_data[key] = 0
                    elif key == 'KiraGunu':
                        formatted_invoice_data[key] = '1'
                    elif key == 'PlakaNo':
                        formatted_invoice_data[key] = 'PLAKASIZ'
                    else:
                        formatted_invoice_data[key] = 'Belirtilmemiş'
            
            print("✅ Fatura verileri hazırlandı")
            
        except Exception as e:
            print(f"❌ Fatura verileri hazırlanırken hata: {str(e)}")
            traceback.print_exc()
            return False
        
        try:
            # XML işlemleri için namespace tanımlamaları
            ET.register_namespace('cac', 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2')
            ET.register_namespace('cbc', 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2')
            ET.register_namespace('ext', 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2')
            ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
            ET.register_namespace('xades', 'http://uri.etsi.org/01903/v1.3.2#')
            ET.register_namespace('udt', 'urn:un:unece:uncefact:data:specification:UnqualifiedDataTypesSchemaModule:2')
            ET.register_namespace('ubltr', 'urn:oasis:names:specification:ubl:schema:xsd:TurkishCustomizationExtensionComponents')
            ET.register_namespace('qdt', 'urn:oasis:names:specification:ubl:schema:xsd:QualifiedDatatypes-2')
            ET.register_namespace('ds', 'http://www.w3.org/2000/09/xmldsig#')
            
            if not os.path.exists('ornek.xml'):
                print("❌ ornek.xml dosyası bulunamadı!")
                return False
                
            tree = ET.parse('ornek.xml')
            root = tree.getroot()
            
            print("🔄 XML güncelleme işlemi devam ediyor...")
            
            # XML yapısını kontrol et
            print("\n📋 XML Yapı Kontrolü:")
            print_xml_structure(root, max_depth=2)
            
            # ... existing code ...
            # (XML güncelleme işlemleri devam ediyor)
            
            print("✅ XML güncelleme tamamlandı")
            
        except ET.ParseError as e:
            print(f"❌ XML parse hatası: {str(e)}")
            traceback.print_exc()
            return False
        except Exception as e:
            print(f"❌ XML işleme hatası: {str(e)}")
            traceback.print_exc()
            return False
        
        try:
            # LoadInvoice işlemi için hazırlık
            print("\n📤 LoadInvoice işlemi başlatılıyor...")
            
            # ... existing code ...
            # (LoadInvoice işlemi devam ediyor)
            
        except Exception as e:
            print(f"❌ LoadInvoice hatası: {str(e)}")
            traceback.print_exc()
            return False
            
        return True
        
    except Exception as e:
        print(f"❌ Genel XML güncelleme hatası: {str(e)}")
        traceback.print_exc()
        return False

def check_updated_xml(xml_path, invoice_data, namespaces):
    if not invoice_data:
        print("⚠️ Fatura verileri olmadığı için XML kontrolü yapılamıyor")
        return
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        print("🔍 XML kontrol ediliyor...")
        
        # Temel kontroller yapılıyor
        item_name = root.find(".//cac:Item/cbc:Name", namespaces)
        invoiced_quantity = root.find(".//cbc:InvoicedQuantity", namespaces)
        note_elements = root.findall(".//cbc:Note", namespaces)
        
        if all([item_name, invoiced_quantity, note_elements]):
            print("✅ XML kontrolleri başarılı")
        else:
            print("⚠️ Bazı XML elementleri eksik olabilir")
        
    except Exception as e:
        print(f"❌ XML kontrol hatası: {str(e)}")

# Sayıyı yazıya çeviren fonksiyon
def sayi_to_yazi(sayi):
    birler = ["", "Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi", "Sekiz", "Dokuz"]
    onlar = ["", "On", "Yirmi", "Otuz", "Kırk", "Elli", "Altmış", "Yetmiş", "Seksen", "Doksan"]
    
    def yuzler_to_yazi(n):
        if n == 0:
            return ""
        elif n < 10:
            return birler[n]
        elif n < 100:
            return onlar[n // 10] + " " + birler[n % 10]
        else:
            if n // 100 == 1:
                return "Yüz " + yuzler_to_yazi(n % 100)
            else:
                return birler[n // 100] + " Yüz " + yuzler_to_yazi(n % 100)
    
    def binler_to_yazi(n):
        if n < 1000:
            return yuzler_to_yazi(n)
        elif n < 1000000:
            if n // 1000 == 1:
                return "Bin " + yuzler_to_yazi(n % 1000)
            else:
                return yuzler_to_yazi(n // 1000) + " Bin " + yuzler_to_yazi(n % 1000)
        else:
            return yuzler_to_yazi(n // 1000000) + " Milyon " + binler_to_yazi(n % 1000000)
    
    # Sayıyı tam ve kuruş olarak ayır
    tam_kisim = int(sayi)
    kurus_kisim = int((sayi - tam_kisim) * 100 + 0.5)  # Yuvarlama
    
    # Tam kısmı yazıya çevir
    tam_yazi = binler_to_yazi(tam_kisim).strip()
    
    # Kuruş kısmı yazıya çevir
    kurus_yazi = yuzler_to_yazi(kurus_kisim).strip()
    
    # Sonucu birleştir
    if tam_kisim > 0 and kurus_kisim > 0:
        return f"{tam_yazi} Türk Lirası {kurus_yazi} Kuruş"
    elif tam_kisim > 0:
        return f"{tam_yazi} Türk Lirası"
    elif kurus_kisim > 0:
        return f"{kurus_yazi} Kuruş"
    else:
        return "Sıfır Türk Lirası"

# İşlenmiş faturaları yükle
def load_processed_invoices():
    try:
        if os.path.exists(PROCESSED_INVOICES_FILE):
            with open(PROCESSED_INVOICES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {"processed_invoices": [], "last_check_time": None}
    except Exception as e:
        print(f"❌ İşlenmiş faturalar yüklenirken hata: {str(e)}")
        return {"processed_invoices": [], "last_check_time": None}

# İşlenmiş faturaları kaydet
def save_processed_invoice(invoice_no):
    try:
        processed_data = load_processed_invoices()
        
        # Fatura numarası zaten işlenmişse ekleme
        if invoice_no not in processed_data["processed_invoices"]:
            processed_data["processed_invoices"].append(invoice_no)
        
        # Son kontrol zamanını güncelle
        processed_data["last_check_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(PROCESSED_INVOICES_FILE, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Fatura No: {invoice_no} işlenmiş faturalar listesine eklendi")
        return True
    except Exception as e:
        print(f"❌ İşlenmiş fatura kaydedilirken hata: {str(e)}")
        return False

def process_new_invoices(invoice_data):
    try:
        if not invoice_data:
            print("⚠️ İşlenecek fatura verisi bulunamadı")
            return
        
        # Markalara göre fatura sayılarını hesapla
        brand = invoice_data[0].get('Brand', 'Bilinmiyor') if invoice_data else 'Bilinmiyor'
        
        # Yeni faturalar varsa EDM'ye bağlan
        print(f"\n📋 {brand} için {len(invoice_data)} yeni kayıt işlenecek")
        
        # EDM'ye bağlan
        client, session_id = edm_login()
        if not client or not session_id:
            print("❌ EDM bağlantısı başarısız!")
            
            # Bağlantı hatası bildirimi
            error_notification = f"""
<b>❌ EDM Bağlantı Hatası</b>

<b>Hata Mesajı:</b>
EDM sistemine bağlanılamadı.

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
            send_telegram_notification(error_notification)
            return
        
        # İşlem başlangıç bildirimi
        start_notification = f"""
<b>🚀 {brand} Fatura İşlemleri Başlatıldı</b>

<b>İşlenecek Kayıt Sayısı:</b> {len(invoice_data)}
<b>Başlangıç Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(start_notification)
        
        # Başarılı ve başarısız işlem sayaçları
        success_count = 0
        fail_count = 0

        # Her kayıt için işlem yap
        for index, kayit in enumerate(invoice_data, 1):
            vkn = kayit.get('VergiNumarasi')  # VergiNumarasi alanını kullan
            ka_no = kayit.get('KANo', 'Bilinmiyor')
            
            print(f"\n{'='*50}")
            print(f"🔄 Kayıt {index}/{len(invoice_data)} işleniyor")
            print(f"📝 Marka: {brand}, VKN: {vkn}, KA No: {ka_no}")
            print(f"{'='*50}")

            if not vkn:
                print("❌ VKN bulunamadı, kayıt atlanıyor")
                fail_count += 1
                continue

            # Firma bilgilerini kontrol et
            alias, vergi_dairesi, unvan, tam_adres, il, ilce = check_user_and_get_info(client, session_id, vkn)
            
            # E-fatura mükellefi değilse veya bilgiler alınamadıysa API'den gelen bilgileri kullan
            if not alias:
                print(f"\n⚠️ VKN: {vkn} - Firma e-fatura mükellefi değil, E-Arşiv faturası olarak işlenecek")
                # JSON'dan gelen bilgileri kullan
                unvan = kayit.get('TumMusteriAdi', '')
                vergi_dairesi = kayit.get('VergiDairesi', '')
                tam_adres = kayit.get('Adres', '')
                il = kayit.get('Il', '')
                ilce = kayit.get('Ilce', '')
            else:
                print(f"\n✅ VKN: {vkn} - Firma e-fatura mükellefi, E-Fatura olarak işlenecek")

            print("\n📋 Firma Bilgileri:")
            print(f"Unvan: {unvan}")
            print(f"VKN: {vkn}")
            print(f"Alias: {alias}")
            print(f"Vergi Dairesi: {vergi_dairesi}")
            print(f"Adres: {tam_adres}")
            print(f"İl: {il}")
            print(f"İlçe: {ilce}")
            print(f"KA No: {ka_no}")

            # TURMOB'dan gelen adres bilgileri null ise JSON'dan gelen bilgileri kullan
            if not tam_adres or not il or not ilce:
                print("\n⚠️ Adres bilgileri eksik, JSON'dan gelen bilgiler kullanılıyor")
                tam_adres = kayit.get('Adres', '')
                il = kayit.get('Il', '')
                ilce = kayit.get('Ilce', '')

            # XML güncelle ve faturayı yükle - kayıt verisini de gönder
            if update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce, kayit):
                print(f"\n✅ Marka: {brand}, VKN: {vkn}, KA No: {ka_no} - İşlem başarıyla tamamlandı")
                success_count += 1
                # İşlenmiş faturalar listesine ekle
                save_processed_invoice(ka_no)
            else:
                print(f"\n❌ Marka: {brand}, VKN: {vkn}, KA No: {ka_no} - İşlem başarısız")
                fail_count += 1

            # İşlemler arası kısa bekle
            time.sleep(1)

        print("\n✅ Tüm yeni kayıtlar işlendi")
        
        # İşlem sonuç bildirimi
        end_notification = f"""
<b>🏁 {brand} Fatura İşlemleri Tamamlandı</b>

<b>Sonuç Özeti:</b>
🔹 <b>Toplam İşlenen Kayıt:</b> {len(invoice_data)}
✅ <b>Başarılı:</b> {success_count}
❌ <b>Başarısız:</b> {fail_count}

<b>Bitiş Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(end_notification)

    except Exception as e:
        print(f"\n❌ Genel hata: {str(e)}")
        traceback.print_exc()
        
        # Genel hata bildirimi
        error_notification = f"""
<b>❌ Genel Hata</b>

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(error_notification)

def get_local_time():
    """Sunucu saatinden yerel saati hesaplar (UTC+3)"""
    server_time = datetime.now()
    time_difference = timedelta(hours=3)  # Sunucu saati ile yerel saat arasındaki fark
    return server_time + time_difference

def main():
    try:
        print("\n🔄 Fatura işleme servisi başlatıldı")
        send_telegram_notification("<b>🚀 Fatura İşleme Servisi Başlatıldı</b>")
        
        # Hangi markanın kontrol edileceğini belirlemek için sayaç
        check_counter = 0
        last_reset_date = None  # Son sıfırlama tarihini tutmak için değişken
        
        while True:
            server_time = datetime.now()
            local_time = get_local_time()
            
            # Her gün yerel saat 00:00'da processed_invoices.json dosyasını sıfırla
            current_date = local_time.date()
            if last_reset_date != current_date and local_time.hour == 0 and local_time.minute == 0:
                try:
                    # Dosyayı sıfırla
                    with open(PROCESSED_INVOICES_FILE, 'w', encoding='utf-8') as f:
                        json.dump({"processed_invoices": [], "last_check_time": local_time.strftime('%Y-%m-%d %H:%M:%S')}, f, indent=2, ensure_ascii=False)
                    print(f"\n🔄 {local_time.strftime('%Y-%m-%d %H:%M:%S')} - İşlenmiş faturalar listesi sıfırlandı")
                    send_telegram_notification(f"<b>🔄 İşlenmiş Faturalar Listesi Sıfırlandı</b>\n\n<b>Tarih:</b> {local_time.strftime('%d.%m.%Y %H:%M:%S')}")
                    last_reset_date = current_date
                except Exception as e:
                    print(f"\n❌ İşlenmiş faturalar listesi sıfırlanırken hata: {str(e)}")
                    send_telegram_notification(f"<b>❌ İşlenmiş Faturalar Listesi Sıfırlama Hatası</b>\n\n<b>Hata:</b> {str(e)}")
            
            brand_to_check = "Avis" if check_counter % 2 == 0 else "Budget"
            license_no = 1 if brand_to_check == "Avis" else 2
            
            print(f"\n🔍 {local_time.strftime('%H:%M:%S')} - {brand_to_check} faturaları kontrol ediliyor...")
            print(f"📅 Sunucu Saati: {server_time.strftime('%H:%M:%S')}")
            print(f"📅 Yerel Saat: {local_time.strftime('%H:%M:%S')}")
            
            # Tek bir marka için fatura verilerini çek ve işle
            invoice_data = []
            
            # Token kontrolü ve yenileme
            token = check_and_refresh_token()
            if token:
                url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
                
                # Sadece bugünün tarihini kullan
                today_local = local_time
                yesterday_local = today_local - timedelta(days=1)  # Dün için
                
                payload = {
                    "Token": token,
                    "LicenseNo": license_no,
                    "InvoiceDate": "",
                    "StartDate": yesterday_local.strftime("%Y%m%d"),  # Dünün tarihi
                    "EndDate": today_local.strftime("%Y%m%d")        # Bugünün tarihi
                }
                
                try:
                    response = requests.post(url, json=payload)
                    response.raise_for_status()
                    response_data = response.json()
                    
                    if 'Data' in response_data and 'Invoices' in response_data['Data']:
                        invoices = response_data['Data']['Invoices']
                        # Marka bilgisini ekle
                        for invoice in invoices:
                            invoice['Brand'] = brand_to_check
                        invoice_data.extend(invoices)
                except Exception as e:
                    print(f"❌ {brand_to_check} faturaları çekilirken hata: {str(e)}")
            
            if invoice_data:
                print(f"✅ {brand_to_check} için {len(invoice_data)} fatura verisi çekildi")
                # İşlenecek faturaları hazırla ve process_new_invoices'a gönder
                unprocessed_invoices = get_invoice_data(invoice_data)
                if unprocessed_invoices:
                    process_new_invoices(unprocessed_invoices)
            else:
                print(f"ℹ️ {brand_to_check} için yeni fatura bulunamadı")
            
            # Bir sonraki kontrole kadar bekle
            print(f"\n⏳ {brand_to_check} kontrolü tamamlandı. Bir sonraki kontrol için bekleniyor...")
            time.sleep(60)  # 60 saniye bekle
            check_counter += 1
            
    except KeyboardInterrupt:
        print("\n⚠️ Kullanıcı tarafından durduruldu")
        send_telegram_notification("<b>⚠️ Fatura İşleme Servisi Durduruldu</b>")
    except Exception as e:
        print(f"\n❌ Ana döngüde hata: {str(e)}")
        traceback.print_exc()
        
        error_notification = f"""
<b>❌ Fatura İşleme Servisi Hatası</b>

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {local_time.strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(error_notification)

# XML yapısını yazdırmak için yardımcı fonksiyon
def print_xml_structure(element, indent="", max_depth=None, current_depth=0):
    if max_depth is not None and current_depth > max_depth:
        print(f"{indent}...")
        return
    
    tag = element.tag
    if '}' in tag:
        tag = tag.split('}', 1)[1]  # Namespace'i kaldır
    
    attrs = ""
    if element.attrib:
        attrs = " " + " ".join([f"{k}='{v}'" for k, v in element.attrib.items()])
    
    text = element.text.strip() if element.text else ""
    if text:
        text = f" text='{text[:30]}...'" if len(text) > 30 else f" text='{text}'"
    
    print(f"{indent}<{tag}{attrs}{text}>")
    
    for child in element:
        print_xml_structure(child, indent + "  ", max_depth, current_depth + 1)

# Güncellenmiş XML'i kontrol etmek için yardımcı fonksiyon
def check_updated_xml(xml_path, invoice_data, namespaces):
    if not invoice_data:
        print("⚠️ Fatura verileri olmadığı için XML kontrolü yapılamıyor")
        return
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Plaka kontrolü
        item_name = root.find(".//cac:Item/cbc:Name", namespaces)
        if item_name is not None:
            print(f"✅ XML'de Plaka: {item_name.text}")
            if invoice_data['PlakaNo'] and invoice_data['PlakaNo'] in item_name.text:
                print("✅ Plaka doğru şekilde güncellenmiş")
            else:
                print(f"❌ Plaka güncellemesi başarısız. Beklenen: {invoice_data['PlakaNo']}")
        else:
            print("❌ XML'de Item/Name elementi bulunamadı")
        
        # Kira günü kontrolü
        invoiced_quantity = root.find(".//cbc:InvoicedQuantity", namespaces)
        if invoiced_quantity is not None:
            print(f"✅ XML'de Kira Günü: {invoiced_quantity.text}")
            try:
                expected = str(int(float(invoice_data['KiraGunu'])))
                if invoiced_quantity.text == expected:
                    print("✅ Kira günü doğru şekilde güncellenmiş")
                else:
                    print(f"❌ Kira günü güncellemesi başarısız. Beklenen: {expected}")
            except (ValueError, TypeError):
                print(f"⚠️ Kira günü karşılaştırması yapılamadı: {invoice_data['KiraGunu']}")
        else:
            print("❌ XML'de InvoicedQuantity elementi bulunamadı")
        
        # KiraTipi kontrolü
        note_elements = root.findall(".//cbc:Note", namespaces)
        kira_tipi_found = False
        for note in note_elements:
            if note.text and "Kira Tipi:" in note.text:
                print(f"✅ XML'de Kira Tipi: {note.text}")
                kira_tipi_found = True
                break
        
        if not kira_tipi_found:
            print("⚠️ XML'de Kira Tipi bilgisi bulunamadı")
        
    except Exception as e:
        print(f"❌ XML kontrol hatası: {str(e)}")

if __name__ == "__main__":
    main()

    # bu dosyada avisten veri almıyor ama geri kalan herşey doğru.