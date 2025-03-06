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

def get_invoice_data():
    """Otokoc API'den fatura verilerini çeker"""
    try:
        # Token kontrolü ve yenileme
        token = check_and_refresh_token()
        if not token:
            print("❌ Geçerli token olmadan fatura verileri çekilemez")
            return []
        
        print("\n📊 Otokoc API'den fatura verileri çekiliyor...")
        
        url = "https://merkezwebapi.otokoc.com.tr/STDealer/GetInvoiceList"
        
        # Dünün tarihini al
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        today = datetime.now().strftime("%Y%m%d")
        
        print(f"🗓️ Tarih aralığı: {yesterday} - {today}")

        payload = {
            "Token": token,
            "LicenseNo": 1,
            "InvoiceDate": "",
            "StartDate": yesterday,
            "EndDate": today
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()  # HTTP hatalarını yakala
        response_data = response.json()
        
        if response_data.get('MessageEN') == "Token is expired":
            print("❌ Token süresi dolmuş, yenileniyor...")
            token = get_otokoc_token()
            if not token:
                return []
            
            # Yeni token ile tekrar dene
            payload["Token"] = token
            response = requests.post(url, json=payload)
            response.raise_for_status()
            response_data = response.json()
        
        if 'Data' not in response_data or 'Invoices' not in response_data['Data']:
            print(f"❌ Otokoc API'den fatura verileri çekilemedi: Geçersiz yanıt formatı")
            print(f"Yanıt: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
            return []

        invoices = response_data['Data']['Invoices']
        print(f"✅ Otokoc API'den {len(invoices)} fatura verisi çekildi")
        
        # Yanıt formatını kontrol et ve debug için yazdır
        if invoices and len(invoices) > 0:
            print(f"\n🔍 Örnek fatura verisi:")
            print(json.dumps(invoices[0], indent=2, ensure_ascii=False))
            
            # Tüm anahtar alanları listele
            print("\n📋 Fatura veri alanları:")
            for key in invoices[0].keys():
                print(f"   - {key}: {invoices[0][key]}")
        
        # Saat 16:00'dan sonraki faturaları filtrele
        filtered_invoices = []
        for invoice in invoices:
            # IslemSaati alanını kontrol et
            islem_saati = invoice.get('IslemSaati', '')
            if not islem_saati:
                # IslemSaati yoksa alternatif alanları kontrol et
                islem_saati = invoice.get('InvoiceDate', '')
            
            if islem_saati:
                try:
                    # Tarih formatını kontrol et
                    if 'T' in islem_saati:
                        # ISO format: 2025-03-05T16:30:00
                        islem_datetime = datetime.fromisoformat(islem_saati.replace('Z', '+00:00'))
                    else:
                        # Diğer olası formatlar
                        try:
                            islem_datetime = datetime.strptime(islem_saati, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            try:
                                islem_datetime = datetime.strptime(islem_saati, '%d.%m.%Y %H:%M:%S')
                            except ValueError:
                                islem_datetime = datetime.strptime(islem_saati, '%d.%m.%Y')
                    
                    # Saat kontrolü - aynı gün 16:00'dan sonra mı?
                    if islem_datetime.hour >= 16:
                        filtered_invoices.append(invoice)
                        print(f"✅ Fatura kabul edildi: {invoice.get('InvoiceNo', 'N/A')} - İşlem Saati: {islem_saati}")
                    else:
                        print(f"⏭️ Fatura filtrelendi (saat 16:00'dan önce): {invoice.get('InvoiceNo', 'N/A')} - İşlem Saati: {islem_saati}")
                except Exception as e:
                    print(f"⚠️ Tarih dönüştürme hatası ({islem_saati}): {str(e)}")
                    # Hata durumunda faturayı dahil et (isteğe bağlı)
                    filtered_invoices.append(invoice)
            else:
                # İşlem saati bilgisi yoksa faturayı dahil et
                filtered_invoices.append(invoice)
                print(f"⚠️ İşlem saati bilgisi olmayan fatura dahil edildi: {invoice.get('InvoiceNo', 'N/A')}")
        
        print(f"🔍 Filtreleme sonucu: {len(filtered_invoices)}/{len(invoices)} fatura işlenecek")
        
        # Ham veriyi logla
        print("\n📋 İşlenecek Faturaların Ham Verileri:")
        for idx, invoice in enumerate(filtered_invoices, 1):
            print(f"\n{'='*50}")
            print(f"Fatura {idx}/{len(filtered_invoices)}")
            print(f"{'='*50}")
            print(json.dumps(invoice, indent=2, ensure_ascii=False))
            print(f"{'='*50}")
        
        # İşlenmiş faturaları yükle
        processed_data = load_processed_invoices()
        processed_invoices = processed_data["processed_invoices"]
        
        # İşlenmemiş faturaları filtrele - KANo kontrolü
        unprocessed_invoices = []
        for invoice in filtered_invoices:
            ka_no = invoice.get('KANo', '')
            
            if ka_no and ka_no not in processed_invoices:
                unprocessed_invoices.append(invoice)
                print(f"✅ Yeni fatura bulundu: {ka_no}")
            else:
                print(f"⏭️ Fatura zaten işlenmiş: {ka_no}")
        
        print(f"🔍 İşlenmemiş fatura sayısı: {len(unprocessed_invoices)}/{len(filtered_invoices)}")
        
        return unprocessed_invoices
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Otokoc API fatura verileri çekme hatası: {str(e)}")
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"❌ Otokoc API fatura verileri çekme hatası: {str(e)}")
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
    print("\n" + "="*50)
    print(f"🔍 CheckUser İşlemi Başlatıldı - VKN: {vkn}")
    print("="*50)
    
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
        print("\n📤 CheckUser İsteği Gönderiliyor...")
        print(f"Request Header: {json.dumps(request_header, indent=2)}")
        print(f"User Data: {json.dumps(user, indent=2)}")
        
        response = client.service.CheckUser(REQUEST_HEADER=request_header, USER=user)
        print("\n📥 CheckUser Yanıtı Alındı")
        
        serialized_response = serialize_object(response)
        print("\nCheckUser Response Details:")
        print("-" * 50)
        print(json.dumps(serialized_response, indent=2, ensure_ascii=False))
        print("-" * 50)

        # Response boş dizi kontrolü
        if not response or len(response) == 0:
            print("\n⚠️ Kullanıcı e-fatura sisteminde bulunamadı")
            print("⚠️ E-Arşiv faturası olarak işleme devam edilecek")
            # E-Arşiv için null değerler döndür, alias null olduğunda E-Arşiv olarak işlenecek
            return None, None, None, None, None, None
        
        print("\n✅ Kullanıcı e-fatura sisteminde bulundu")
        
        # Response'un ilk elemanından ALIAS değerini al
        first_user = response[0]
        alias = first_user.ALIAS if hasattr(first_user, 'ALIAS') else None
        print(f"📧 Alias: {alias}")
        
        if not alias:
            print("\n⚠️ Alias bulunamadı")
            print("⚠️ E-Arşiv faturası olarak işleme devam edilecek")
            return None, None, None, None, None, None
            
        # TURMOB bilgilerini al
        print("\n🔄 TURMOB Bilgileri Alınıyor...")
        turmob_header = {
            "SESSION_ID": session_id,
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": datetime.now().strftime("%Y-%m-%d"),
            "REASON": "test",
            "APPLICATION_NAME": "EDMTEST",
            "HOSTNAME": "BALCIAS",
            "CHANNEL_NAME": "EDM",
            "COMPRESSED": "N"
        }
        
        try:
            print("\n📤 TURMOB İsteği Gönderiliyor...")
            print(f"VKN: {vkn}")
            print(f"Session ID: {session_id}")
            print(f"TURMOB Request Header: {json.dumps(turmob_header, indent=2)}")
            
            try:
                turmob_response = client.service.GetTurmob(REQUEST_HEADER=turmob_header, VKN=vkn)
            except zeep.exceptions.Fault as soap_error:
                print(f"\n❌ SOAP Hatası:")
                print(f"Hata Mesajı: {soap_error.message}")
                if hasattr(soap_error, 'detail'):
                    detail_xml = ET.tostring(soap_error.detail, encoding='unicode')
                    print(f"Hata Detayı XML: {detail_xml}")
                print(f"Hata Kodu: {getattr(soap_error, 'code', 'Kod yok')}")
                return alias, None, None, None, None, None
            
            print("\n📥 TURMOB Ham Yanıt:")
            print("-" * 50)
            print(turmob_response)
            print("-" * 50)
            
            if hasattr(turmob_response, 'ERROR'):
                print(f"\n❌ TURMOB Hatası: {turmob_response.ERROR}")
                return alias, None, None, None, None, None
            
            serialized_turmob = serialize_object(turmob_response)
            print("\n📥 TURMOB Serialize Edilmiş Yanıt:")
            print("-" * 50)
            print(json.dumps(serialized_turmob, indent=2, ensure_ascii=False))
            print("-" * 50)
            
            # Yanıt kontrolü
            if not serialized_turmob:
                print("\n⚠️ TURMOB yanıtı boş")
                return alias, None, None, None, None, None
            
            # TURMOB bilgilerini al
            vergi_dairesi = serialized_turmob.get('vergiDairesiAdi', '')
            unvan = serialized_turmob.get('kimlikUnvani', '')
            
            # Adres bilgileri
            adres_bilgileri = serialized_turmob.get('adresBilgileri', {}).get('AdresBilgileri', [{}])[0]
            
            # Adres bileşenlerini birleştir
            adres_parcalari = [
                adres_bilgileri.get('mahalleSemt', ''),
                adres_bilgileri.get('caddeSokak', ''),
                adres_bilgileri.get('disKapiNo', ''),
                adres_bilgileri.get('icKapiNo', '')
            ]
            tam_adres = ' '.join(filter(None, adres_parcalari))
            il = adres_bilgileri.get('ilAdi', '')
            ilce = adres_bilgileri.get('ilceAdi', '')
            
            print("\n📋 TURMOB Bilgileri:")
            print(f"Vergi Dairesi: {vergi_dairesi}")
            print(f"Unvan: {unvan}")
            print(f"Adres: {tam_adres}")
            print(f"İl: {il}")
            print(f"İlçe: {ilce}")
            
            return alias, vergi_dairesi, unvan, tam_adres, il, ilce
            
        except Exception as e:
            print(f"\n❌ TURMOB bilgileri alınırken hata: {str(e)}")
            traceback.print_exc()
            return alias, None, None, None, None, None

    except Exception as e:
        print(f"\n❌ CheckUser işleminde hata: {str(e)}")
        traceback.print_exc()
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
        
        # E-Arşiv kontrolü
        is_earchive = not alias  # alias yoksa E-Arşiv
        print(f"✅ Fatura tipi: {'E-Arşiv' if is_earchive else 'E-Fatura'}")
        
        # Kayıt verileri varsa, bunları kullan
        if kayit:
            # Kayıt verilerini formatla
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
                'PlakaNo': kayit.get('PlakaNo', '')
            }
            
            # Boş değerleri kontrol et ve varsayılan değerlerle doldur
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
            
            # Debug için tüm değerleri yazdır
            print("\n🔍 Fatura verileri (XML güncellemesi için):")
            for key, value in formatted_invoice_data.items():
                print(f"   {key}: {value} (Tip: {type(value)})")
            
            print(f"✅ Fatura verileri hazırlandı: {json.dumps(formatted_invoice_data, indent=2, ensure_ascii=False)}")
        else:
            print("⚠️ Kayıt verileri bulunamadı, sadece müşteri bilgileri güncellenecek")
            formatted_invoice_data = None
        
        # XML dosyasını oku ve namespace'leri koru
        ET.register_namespace('cac', 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2')
        ET.register_namespace('cbc', 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2')
        ET.register_namespace('ext', 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2')
        ET.register_namespace('xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        ET.register_namespace('xades', 'http://uri.etsi.org/01903/v1.3.2#')
        ET.register_namespace('udt', 'urn:un:unece:uncefact:data:specification:UnqualifiedDataTypesSchemaModule:2')
        ET.register_namespace('ubltr', 'urn:oasis:names:specification:ubl:schema:xsd:TurkishCustomizationExtensionComponents')
        ET.register_namespace('qdt', 'urn:oasis:names:specification:ubl:schema:xsd:QualifiedDatatypes-2')
        ET.register_namespace('ds', 'http://www.w3.org/2000/09/xmldsig#')
        
        # XML dosyasını kontrol et
        if not os.path.exists('ornek.xml'):
            print("❌ ornek.xml dosyası bulunamadı!")
            return False
            
        tree = ET.parse('ornek.xml')
        root = tree.getroot()
        
        # XML yapısını debug için yazdır
        print("\n🔍 XML yapısı analiz ediliyor...")
        print_xml_structure(root, max_depth=3)
        
        namespaces = {
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'
        }

        # Güncel tarih ve saat
        current_date = datetime.now().strftime('%Y-%m-%d')
        current_time = datetime.now().strftime('%H:%M:%S')

        # Tüm IssueDate elementlerini güncelle
        for issue_date in root.findall('.//cbc:IssueDate', namespaces):
            issue_date.text = current_date
            print(f"✅ IssueDate güncellendi: {current_date}")

        # IssueTime elementini güncelle
        issue_time = root.find('.//cbc:IssueTime', namespaces)
        if issue_time is not None:
            issue_time.text = current_time
            print(f"✅ IssueTime güncellendi: {current_time}")

        # UUID ve ID güncelle
        uuid_element = root.find('.//cbc:UUID', namespaces)
        id_element = root.find('.//cbc:ID', namespaces)
        
        # Yeni UUID oluştur
        new_uuid = str(uuid.uuid4())
        
        # UUID güncelle
        if uuid_element is not None:
            uuid_element.text = new_uuid
            print(f"✅ UUID güncellendi: {new_uuid}")
        
        # ProfileID güncelleme - E-Arşiv kontrolü
        profile_id = root.find('.//cbc:ProfileID', namespaces)
        if profile_id is not None:
            if is_earchive:
                profile_id.text = "EARSIVFATURA"
                print("✅ ProfileID EARSIVFATURA olarak güncellendi")
            else:
                profile_id.text = "TICARIFATURA"
                print("✅ ProfileID TICARIFATURA olarak güncellendi")

        # AccountingCustomerParty güncellemeleri
        customer = root.find('.//cac:AccountingCustomerParty', namespaces)
        if customer is not None and formatted_invoice_data:
            party = customer.find('.//cac:Party', namespaces)
            if party is not None:
                # VKN/TCKN güncelleme
                id_element = party.find('.//cac:PartyIdentification/cbc:ID[@schemeID]', namespaces)
                if id_element is not None:
                    vkn_value = formatted_invoice_data['VergiNumarasi'].strip()
                    id_element.text = vkn_value
                    
                    # VKN/TCKN kontrolü ve schemeID düzeltmesi
                    if len(vkn_value) == 11:  # 11 hane ise TCKN
                        id_element.set('schemeID', 'TCKN')
                        print(f"✅ Müşteri TCKN güncellendi: {vkn_value} (schemeID=TCKN)")
                    else:  # 10 hane veya diğer durumlar için VKN
                        id_element.set('schemeID', 'VKN')
                        print(f"✅ Müşteri VKN güncellendi: {vkn_value} (schemeID=VKN)")
                
                # Müşteri adı güncelleme - E-Fatura durumunda TURMOB'dan gelen unvan bilgisini kullan
                party_name = party.find('.//cac:PartyName/cbc:Name', namespaces)
                if party_name is not None:
                    # E-Fatura durumunda ve unvan bilgisi varsa TURMOB'dan gelen unvanı kullan
                    if not is_earchive and unvan:
                        party_name.text = unvan
                        print(f"✅ Müşteri adı TURMOB'dan alındı: {unvan}")
                    else:
                        party_name.text = formatted_invoice_data['TumMusteriAdi']
                        print(f"✅ Müşteri adı JSON'dan alındı: {formatted_invoice_data['TumMusteriAdi']}")
                
                # Kişi bilgileri güncelleme
                person = party.find('.//cac:Person', namespaces)
                if person is not None:
                    # Kullanılacak isim - E-Fatura durumunda TURMOB'dan gelen unvanı kullan
                    customer_name = unvan if not is_earchive and unvan else formatted_invoice_data['TumMusteriAdi']
                    
                    if customer_name:
                        # İsim parçalarına ayır
                        name_parts = customer_name.split()
                        if len(name_parts) > 1:
                            # Son kelime soyad, geri kalanı ad
                            first_name = ' '.join(name_parts[:-1])
                            family_name = name_parts[-1]
                        else:
                            # Tek kelime varsa, tamamı ad olsun
                            first_name = customer_name
                            family_name = "-"
                        
                        # FirstName güncelleme
                        first_name_element = person.find('./cbc:FirstName', namespaces)
                        if first_name_element is not None:
                            first_name_element.text = first_name
                            print(f"✅ Müşteri adı güncellendi: {first_name}")
                        
                        # FamilyName güncelleme
                        family_name_element = person.find('./cbc:FamilyName', namespaces)
                        if family_name_element is not None:
                            family_name_element.text = family_name
                            print(f"✅ Müşteri soyadı güncellendi: {family_name}")

        # Kayıt verileri varsa, fatura detaylarını güncelle
        if formatted_invoice_data:
            # Item altındaki cbc:Name elementini PlakaNo ile güncelle
            item_name_element = root.find(".//cac:Item/cbc:Name", namespaces)
            if item_name_element is not None and formatted_invoice_data['PlakaNo']:
                item_name_element.text = f"{formatted_invoice_data['PlakaNo']} PLAKALI ARAÇ KİRALAMA BEDELİ"
                print(f"✅ Plaka güncellendi: {item_name_element.text}")
            else:
                # Alternatif element arama
                all_name_elements = root.findall(".//cbc:Name", namespaces)
                print(f"⚠️ Plaka için Item/Name elementi bulunamadı. Toplam {len(all_name_elements)} Name elementi var.")
                
                # Alternatif olarak Description elementini dene
                description_element = root.find(".//cbc:Description", namespaces)
                if description_element is not None and formatted_invoice_data['PlakaNo']:
                    description_element.text = f"{formatted_invoice_data['PlakaNo']} PLAKALI ARAÇ KİRALAMA BEDELİ"
                    print(f"✅ Plaka (Description elementinde) güncellendi: {description_element.text}")
                else:
                    print(f"❌ Plaka güncellenemedi: PlakaNo={formatted_invoice_data['PlakaNo']}")

            # InvoicedQuantity güncelleme (Kira günü)
            invoiced_quantity_element = root.find(".//cbc:InvoicedQuantity", namespaces)
            if invoiced_quantity_element is not None:
                try:
                    # Kira günü değerini kontrol et
                    kira_gunu = formatted_invoice_data['KiraGunu']
                    if isinstance(kira_gunu, str) and not kira_gunu.strip():
                        kira_gunu = '1'  # Boş string ise varsayılan değer
                    
                    invoiced_quantity_element.text = str(int(float(kira_gunu)))
                    print(f"✅ Kira günü güncellendi: {invoiced_quantity_element.text}")
                except (ValueError, TypeError) as e:
                    print(f"⚠️ Kira günü güncellenemedi: {e}, KiraGunu={formatted_invoice_data['KiraGunu']}")
                    invoiced_quantity_element.text = "1"  # Varsayılan değer
                    print(f"✅ Kira günü varsayılan değere ayarlandı: {invoiced_quantity_element.text}")
            else:
                # Alternatif element arama
                quantity_elements = root.findall(".//*[contains(local-name(), 'Quantity')]", namespaces)
                print(f"⚠️ InvoicedQuantity elementi bulunamadı. Toplam {len(quantity_elements)} Quantity elementi var.")
                
                if quantity_elements:
                    # İlk quantity elementini güncelle
                    try:
                        quantity_elements[0].text = str(int(float(formatted_invoice_data['KiraGunu'])))
                        print(f"✅ Alternatif Quantity elementi güncellendi: {quantity_elements[0].text}")
                    except (ValueError, TypeError, IndexError) as e:
                        print(f"❌ Alternatif Quantity elementi güncellenemedi: {e}")

            # PriceAmount güncelleme (Günlük fiyat)
            price_amount_element = root.find(".//cbc:PriceAmount", namespaces)
            if price_amount_element is not None:
                try:
                    # KDVsizTutar ve KiraGunu değerlerini kontrol et
                    kdvsiz_tutar = float(formatted_invoice_data['KDVsizTutar'])
                    kira_gunu = float(formatted_invoice_data['KiraGunu']) if formatted_invoice_data['KiraGunu'] else 1
                    
                    if kira_gunu > 0:
                        price_per_day = kdvsiz_tutar / kira_gunu
                        price_amount_element.text = f"{price_per_day:.2f}"
                        print(f"✅ Günlük fiyat güncellendi: {price_amount_element.text}")
                    else:
                        price_amount_element.text = f"{kdvsiz_tutar:.2f}"
                        print("⚠️ Kira günü sıfır olduğu için toplam tutar günlük fiyat olarak ayarlandı")
                except (ValueError, ZeroDivisionError) as e:
                    price_amount_element.text = "0.00"
                    print(f"⚠️ Günlük fiyat hesaplanamadı: {e}, varsayılan değer 0.00 olarak ayarlandı")

            # KDV Oranı güncelleme
            percent_element = root.find(".//cbc:Percent", namespaces)
            if percent_element is not None:
                try:
                    percent_element.text = str(int(float(formatted_invoice_data['KDVOrani'])))
                    print(f"✅ KDV oranı güncellendi: {percent_element.text}")
                except (ValueError, TypeError) as e:
                    print(f"⚠️ KDV oranı güncellenemedi: {e}, KDVOrani={formatted_invoice_data['KDVOrani']}")
                    percent_element.text = "0"  # Varsayılan değer

            # TaxAmount güncelleme (KDV tutarı)
            tax_amount_elements = root.findall(".//cbc:TaxAmount", namespaces)
            for tax_amount_element in tax_amount_elements:
                try:
                    kdv_tutari = float(formatted_invoice_data['KDVTutari'])
                    tax_amount_element.text = f"{kdv_tutari:.2f}"
                    print(f"✅ KDV tutarı güncellendi: {tax_amount_element.text}")
                except (ValueError, TypeError) as e:
                    print(f"⚠️ KDV tutarı güncellenemedi: {e}, KDVTutari={formatted_invoice_data['KDVTutari']}")
                    tax_amount_element.text = "0.00"  # Varsayılan değer

            # KDVsiz tutar ile güncellenecek elementler
            elements_to_update_kdvsiz = [
                ".//cbc:TaxableAmount",
                ".//cbc:LineExtensionAmount",
                ".//cbc:TaxExclusiveAmount"
            ]

            for xpath in elements_to_update_kdvsiz:
                elements = root.findall(xpath, namespaces)
                for element in elements:
                    if element is not None:
                        try:
                            kdvsiz_tutar = float(formatted_invoice_data['KDVsizTutar'])
                            element.text = f"{kdvsiz_tutar:.2f}"
                            print(f"✅ KDVsiz tutar güncellendi ({xpath}): {element.text}")
                        except (ValueError, TypeError) as e:
                            print(f"⚠️ KDVsiz tutar güncellenemedi: {e}, KDVsizTutar={formatted_invoice_data['KDVsizTutar']}")
                            element.text = "0.00"  # Varsayılan değer

            # KDVli tutar ile güncellenecek elementler
            elements_to_update_kdvli = [
                ".//cbc:TaxInclusiveAmount",
                ".//cbc:PayableAmount"
            ]

            for xpath in elements_to_update_kdvli:
                element = root.find(xpath, namespaces)
                if element is not None:
                    try:
                        kdvli_tutar = float(formatted_invoice_data['KDVliToplamTutar'])
                        element.text = f"{kdvli_tutar:.2f}"
                        print(f"✅ KDVli tutar güncellendi ({xpath}): {element.text}")
                    except (ValueError, TypeError) as e:
                        print(f"⚠️ KDVli tutar güncellenemedi: {e}, KDVliToplamTutar={formatted_invoice_data['KDVliToplamTutar']}")
                        element.text = "0.00"  # Varsayılan değer

            # Toplam tutarı yazıya çevir
            try:
                toplam_tutar = float(formatted_invoice_data['KDVliToplamTutar'])
                tutar_yazi = sayi_to_yazi(toplam_tutar)
            except (ValueError, TypeError) as e:
                print(f"⚠️ Tutar yazıya çevrilemedi: {e}")
                tutar_yazi = "Sıfır TL"

            # Note elementlerini güncelle
            note_elements = root.findall(".//cbc:Note", namespaces)
            if note_elements:
                # İlk Note elementini tutar yazısı için kullan
                if len(note_elements) >= 1:
                    note_elements[0].text = f"Yazı ile: # {tutar_yazi} #"
                    print(f"✅ Tutar yazı ile güncellendi: {note_elements[0].text}")
                
                # İkinci Note elementini KA numarası için kullan
                if len(note_elements) >= 2:
                    note_elements[1].text = f"KA: {formatted_invoice_data['KANo']}"
                    print(f"✅ KA numarası güncellendi: {note_elements[1].text}")
                
                # Üçüncü Note elementini KiraTipi için kullan
                if len(note_elements) >= 3 and formatted_invoice_data['KiraTipi']:
                    note_elements[2].text = f"Kira Tipi: {formatted_invoice_data['KiraTipi']}"
                    print(f"✅ KiraTipi (Note elementinde) güncellendi: {note_elements[2].text}")
                elif formatted_invoice_data['KiraTipi']:
                    # Yeni bir Note elementi ekle
                    invoice_lines = root.findall(".//cac:InvoiceLine", namespaces)
                    if invoice_lines:
                        invoice_line = invoice_lines[0]
                        # Yeni Note elementi oluştur
                        new_note = ET.SubElement(invoice_line, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}Note')
                        new_note.text = f"Kira Tipi: {formatted_invoice_data['KiraTipi']}"
                        print(f"✅ KiraTipi için yeni Note elementi eklendi: {new_note.text}")
                    else:
                        print("❌ KiraTipi için InvoiceLine elementi bulunamadı")

        # Güncellenmiş XML'i kaydet
        updated_xml_path = 'updated_invoice.xml'
        tree.write(updated_xml_path, encoding='UTF-8', xml_declaration=True)
        print(f"✅ Güncellenmiş XML kaydedildi: {updated_xml_path}")
        
        # Güncellenmiş XML'i kontrol et
        print("\n🔍 Güncellenmiş XML kontrol ediliyor...")
        check_updated_xml(updated_xml_path, formatted_invoice_data, namespaces)
        
        # XML dosyasını oku ve base64 ile kodla
        with open(updated_xml_path, 'rb') as f:
            xml_content = f.read()
        
        encoded_content = base64.b64encode(xml_content).decode('utf-8')
        print(f"✅ XML içeriği base64 ile kodlandı ({len(encoded_content)} karakter)")
        
        # LoadInvoice request header
        request_header = {
            "SESSION_ID": session_id,
            "CLIENT_TXN_ID": str(uuid.uuid4()),
            "ACTION_DATE": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+03:00",
            "REASON": "E-fatura/E-Arşiv gönder-al testleri için",
            "APPLICATION_NAME": "EDM MINI CONNECTOR v1.0",
            "HOSTNAME": "MDORA17",
            "CHANNEL_NAME": "TEST",
            "COMPRESSED": "N"
        }

        # Sender bilgileri
        sender = {
            "vkn": "8930043435",
            "alias": "urn:mail:urartugb@edmbilisim.com"
        }

        # Receiver bilgileri - E-Arşiv için özel ayarlama
        if is_earchive:
            receiver = {
                "vkn": vkn,
                "alias": ""  # E-Arşiv için boş alias
            }
            print("⚠️ E-Arşiv faturası için boş alias kullanılıyor")
        else:
            receiver = {
                "vkn": vkn,
                "alias": alias  # CheckUser'dan gelen tam alias değeri
            }

        print("\n📤 LoadInvoice Bilgileri:")
        print(f"Sender: {json.dumps(sender, indent=2)}")
        print(f"Receiver: {json.dumps(receiver, indent=2)}")
        print(f"E-Arşiv mi?: {is_earchive}")

        # Invoice içeriği
        invoice = {
            "TRXID": "0",
            "HEADER": {
                "SENDER": sender["vkn"],
                "RECEIVER": receiver["vkn"],
                "FROM": sender["alias"],
                "TO": receiver["alias"] if not is_earchive else "",  # E-Arşiv için TO alanını boş bırak
                "INTERNETSALES": False,
                "EARCHIVE": is_earchive,  # E-Arşiv durumuna göre ayarla
                "EARCHIVE_REPORT_SENDDATE": "0001-01-01",
                "CANCEL_EARCHIVE_REPORT_SENDDATE": "0001-01-01",
            },
            "CONTENT": encoded_content
        }

        # Maksimum deneme sayısı
        max_attempts = 3
        retry_delay = 5  # saniye
        
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"\n📤 LoadInvoice isteği gönderiliyor... (Deneme {attempt}/{max_attempts})")
                print(f"Request Header: {json.dumps(request_header, indent=2)}")
                
                # Parametreleri bir sözlük olarak hazırla
                load_params = {
                    "REQUEST_HEADER": request_header,
                    "SENDER": sender,
                    "RECEIVER": receiver,
                    "INVOICE": [invoice],
                    "GENERATEINVOICEIDONLOAD": True
                }
                
                # Timeout ve detaylı loglama ekle
                import time
                print("⏳ LoadInvoice isteği başlatılıyor...")
                start_time = time.time()
                
                # İsteği gönder
                response = client.service.LoadInvoice(**load_params)
                
                end_time = time.time()
                print(f"✅ LoadInvoice isteği tamamlandı ({end_time - start_time:.2f} saniye)")
                
                # Basit yanıt kontrolü
                print("\n📥 LoadInvoice yanıtı alındı")
                
                # Yanıt içeriğini basit şekilde kontrol et
                if response is None:
                    print("⚠️ LoadInvoice yanıtı boş (None)")
                    if attempt < max_attempts:
                        print(f"⏳ {retry_delay} saniye bekleyip tekrar deneniyor...")
                        time.sleep(retry_delay)
                        continue
                
                # Yanıtı basit şekilde logla
                print(f"Yanıt tipi: {type(response)}")
                
                # Başarı kontrolü - basitleştirilmiş
                success = False
                error_msg = ""
                
                try:
                    if hasattr(response, 'INVOICE') and response.INVOICE:
                        invoice_header = response.INVOICE[0].HEADER
                        if hasattr(invoice_header, 'STATUS'):
                            status = invoice_header.STATUS
                            print(f"Fatura durumu: {status}")
                            
                            if status == 'LOAD - SUCCEED':
                                success = True
                                # Fatura ID ve UUID bilgilerini yazdır
                                if hasattr(invoice_header, 'ID'):
                                    print(f"📄 Fatura ID: {invoice_header.ID}")
                                if hasattr(invoice_header, 'UUID'):
                                    print(f"🔑 Fatura UUID: {invoice_header.UUID}")
                    
                    if hasattr(response, 'ERROR'):
                        error_msg = response.ERROR
                except Exception as e:
                    print(f"⚠️ Yanıt işlenirken hata: {str(e)}")
                
                if success:
                    print("\n✅ Fatura başarıyla yüklendi")
                    
                    # Telegram bildirimi gönder
                    fatura_tipi = "E-Arşiv" if is_earchive else "E-Fatura"
                    fatura_id = invoice_header.ID if hasattr(invoice_header, 'ID') else "Bilinmiyor"
                    fatura_uuid = invoice_header.UUID if hasattr(invoice_header, 'UUID') else "Bilinmiyor"
                    
                    notification_message = f"""
<b>✅ Fatura Başarıyla Yüklendi</b>

<b>Fatura Bilgileri:</b>
🔹 <b>Fatura Tipi:</b> {fatura_tipi}
🔹 <b>Fatura ID:</b> {fatura_id}
🔹 <b>Fatura UUID:</b> {fatura_uuid}
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}
🔹 <b>KA No:</b> {formatted_invoice_data.get('KANo', 'Bilinmiyor') if formatted_invoice_data else 'Bilinmiyor'}

<b>Tutar Bilgileri:</b>
"""
                    if formatted_invoice_data:
                        notification_message += f"""
🔹 <b>KDV Oranı:</b> %{formatted_invoice_data['KDVOrani']}
🔹 <b>KDV Tutarı:</b> {formatted_invoice_data['KDVTutari']} TL
🔹 <b>KDV'siz Tutar:</b> {formatted_invoice_data['KDVsizTutar']} TL
🔹 <b>Toplam Tutar:</b> {formatted_invoice_data['KDVliToplamTutar']} TL
"""
                    
                    notification_message += f"""
<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
                    
                    # Bildirimi gönder
                    send_telegram_notification(notification_message)
                    
                    # Başarılı işlemi kaydet
                    if formatted_invoice_data and 'KANo' in formatted_invoice_data and formatted_invoice_data['KANo']:
                        save_processed_invoice(formatted_invoice_data['KANo'])
                    
                    return True
                else:
                    if error_msg:
                        print(f"\n❌ Fatura yükleme başarısız: {error_msg}")
                        
                        # GİB E-Fatura kapsamında bulunmuyor hatası kontrolü
                        if "GİB E-Fatura kapsamında bulunmuyor" in error_msg:
                            print("⚠️ GİB sisteminde geçici bir sorun olabilir.")
                            if attempt < max_attempts:
                                print(f"⏳ {retry_delay} saniye bekleyip tekrar deneniyor...")
                                time.sleep(retry_delay)
                                # Yeni bir session ID al
                                try:
                                    print("🔄 Yeni oturum açılıyor...")
                                    new_client, new_session_id = edm_login()
                                    if new_client and new_session_id:
                                        client = new_client
                                        session_id = new_session_id
                                        request_header["SESSION_ID"] = session_id
                                        print(f"✅ Yeni oturum açıldı: {session_id}")
                                    else:
                                        print("❌ Yeni oturum açılamadı")
                                except Exception as login_error:
                                    print(f"❌ Yeni oturum açma hatası: {str(login_error)}")
                                continue
                        
                        # UUID çakışması hatası kontrolü
                        if "Daha önce yüklediğiniz bir fatura" in error_msg:
                            print("⚠️ UUID çakışması tespit edildi.")
                            if attempt < max_attempts:
                                print(f"⏳ Yeni UUID ile tekrar deneniyor...")
                                # Yeni UUID oluştur
                                new_uuid = str(uuid.uuid4())
                                uuid_element = root.find('.//cbc:UUID', namespaces)
                                if uuid_element is not None:
                                    uuid_element.text = new_uuid
                                    print(f"✅ UUID güncellendi: {new_uuid}")
                                    
                                    # Güncellenmiş XML'i kaydet
                                    tree.write(updated_xml_path, encoding='UTF-8', xml_declaration=True)
                                    
                                    # XML dosyasını oku ve base64 ile kodla
                                    with open(updated_xml_path, 'rb') as f:
                                        xml_content = f.read()
                                    
                                    encoded_content = base64.b64encode(xml_content).decode('utf-8')
                                    invoice["CONTENT"] = encoded_content
                                    
                                    continue
                    else:
                        print("\n❌ Fatura yükleme başarısız")
                        
                        # Maksimum deneme sayısına ulaşıldıysa hata bildirimi gönder
                        if attempt >= max_attempts:
                            error_notification = f"""
<b>❌ Fatura Yükleme Başarısız</b>

<b>Fatura Bilgileri:</b>
🔹 <b>Fatura Tipi:</b> {"E-Arşiv" if is_earchive else "E-Fatura"}
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}

<b>Hata Mesajı:</b>
Bilinmeyen hata

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
                            send_telegram_notification(error_notification)
                    
                    if attempt < max_attempts:
                        print(f"⏳ {retry_delay} saniye bekleyip tekrar deneniyor...")
                        time.sleep(retry_delay)
                        continue
                    
                    return False
                    
            except Exception as e:
                print(f"\n❌ LoadInvoice hatası: {str(e)}")
                traceback.print_exc()
                
                # Maksimum deneme sayısına ulaşıldıysa hata bildirimi gönder
                if attempt >= max_attempts:
                    error_notification = f"""
<b>❌ LoadInvoice İşlemi Hatası</b>

<b>Fatura Bilgileri:</b>
🔹 <b>Fatura Tipi:</b> {"E-Arşiv" if is_earchive else "E-Fatura"}
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
                    send_telegram_notification(error_notification)
                
                if attempt < max_attempts:
                    print(f"⏳ {retry_delay} saniye bekleyip tekrar deneniyor... (Deneme {attempt}/{max_attempts})")
                    time.sleep(retry_delay)
                    continue
                
                return False
        
        # Tüm denemeler başarısız oldu
        print("❌ Maksimum deneme sayısına ulaşıldı. İşlem başarısız.")
        return False
            
    except Exception as e:
        print(f"\n❌ XML güncelleme hatası: {str(e)}")
        traceback.print_exc()
        
        # XML güncelleme hatası bildirimi gönder
        error_notification = f"""
<b>❌ XML Güncelleme Hatası</b>

<b>Fatura Bilgileri:</b>
🔹 <b>VKN/TCKN:</b> {vkn}
🔹 <b>Müşteri:</b> {unvan}

<b>Hata Mesajı:</b>
{str(e)}

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(error_notification)
        
        return False

# Sayıyı yazıya çeviren fonksiyon
def sayi_to_yazi(sayi):
    birler = ["", "BİR", "İKİ", "ÜÇ", "DÖRT", "BEŞ", "ALTI", "YEDİ", "SEKİZ", "DOKUZ"]
    onlar = ["", "ON", "YİRMİ", "OTUZ", "KIRK", "ELLİ", "ALTMIŞ", "YETMİŞ", "SEKSEN", "DOKSAN"]
    
    def yuzler_to_yazi(n):
        if n == 0:
            return ""
        elif n < 10:
            return birler[n]
        elif n < 100:
            return onlar[n // 10] + " " + birler[n % 10]
        else:
            if n // 100 == 1:
                return "YÜZ " + yuzler_to_yazi(n % 100)
            else:
                return birler[n // 100] + " YÜZ " + yuzler_to_yazi(n % 100)
    
    def binler_to_yazi(n):
        if n < 1000:
            return yuzler_to_yazi(n)
        elif n < 1000000:
            if n // 1000 == 1:
                return "BİN " + yuzler_to_yazi(n % 1000)
            else:
                return yuzler_to_yazi(n // 1000) + " BİN " + yuzler_to_yazi(n % 1000)
        else:
            return yuzler_to_yazi(n // 1000000) + " MİLYON " + binler_to_yazi(n % 1000000)
    
    # Sayıyı tam ve kuruş olarak ayır
    tam_kisim = int(sayi)
    kurus_kisim = int((sayi - tam_kisim) * 100 + 0.5)  # Yuvarlama
    
    # Tam kısmı yazıya çevir
    tam_yazi = binler_to_yazi(tam_kisim).strip()
    
    # Kuruş kısmı yazıya çevir
    kurus_yazi = yuzler_to_yazi(kurus_kisim).strip()
    
    # Sonucu birleştir
    if tam_kisim > 0 and kurus_kisim > 0:
        return f"{tam_yazi} TÜRK LİRASI {kurus_yazi} KURUŞ"
    elif tam_kisim > 0:
        return f"{tam_yazi} TÜRK LİRASI"
    elif kurus_kisim > 0:
        return f"{kurus_yazi} KURUŞ"
    else:
        return "SIFIR TÜRK LİRASI"

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

def process_new_invoices():
    try:
        # Fatura verilerini Otokoc API'den çek
        invoice_data = get_invoice_data()
        
        if not invoice_data:
            print("⚠️ İşlenecek fatura verisi bulunamadı")
            return
        
        # Yeni faturalar varsa EDM'ye bağlan
        print(f"\n📋 Toplam {len(invoice_data)} yeni kayıt işlenecek")
        
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
<b>🚀 Yeni Fatura İşlemleri Başlatıldı</b>

<b>Toplam İşlenecek Kayıt:</b> {len(invoice_data)}
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
            print(f"📝 VKN: {vkn}, KA No: {ka_no}")
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
                print(f"\n✅ VKN: {vkn}, KA No: {ka_no} - İşlem başarıyla tamamlandı")
                success_count += 1
                # İşlenmiş faturalar listesine ekle
                save_processed_invoice(ka_no)
            else:
                print(f"\n❌ VKN: {vkn}, KA No: {ka_no} - İşlem başarısız")
                fail_count += 1

            # İşlemler arası kısa bekle
            time.sleep(1)

        print("\n✅ Tüm yeni kayıtlar işlendi")
        
        # İşlem sonuç bildirimi
        end_notification = f"""
<b>🏁 Yeni Fatura İşlemleri Tamamlandı</b>

<b>Sonuç Özeti:</b>
🔹 <b>Toplam İşlenen Kayıt:</b> {len(invoice_data)}
🔹 <b>Başarılı İşlem:</b> {success_count}
🔹 <b>Başarısız İşlem:</b> {fail_count}

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

def main():
    try:
        print("\n🔄 Fatura işleme servisi başlatıldı")
        send_telegram_notification("<b>🚀 Fatura İşleme Servisi Başlatıldı</b>")
        
        # İlk çalıştırmada tüm faturaları işle
        process_new_invoices()
        
        # Her 1 dakikada bir yeni faturaları kontrol et
        while True:
            print(f"\n⏳ Bir sonraki kontrol için bekleniyor... ({datetime.now().strftime('%H:%M:%S')})")
            time.sleep(60)  # 60 saniye bekle
            print(f"\n🔍 Yeni faturalar kontrol ediliyor... ({datetime.now().strftime('%H:%M:%S')})")
            
            # Yeni faturaları işle
            process_new_invoices()
            
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

<b>İşlem Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
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