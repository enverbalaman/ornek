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
import socket

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
        
        # Verileri kiralamaVeri.json formatına dönüştür
        formatted_invoices = []
        for invoice in filtered_invoices:
            # InvoiceNo veya KANo alanını kontrol et
            ka_no = invoice.get('InvoiceNo', '')
            if not ka_no:
                ka_no = invoice.get('KANo', '')
                if not ka_no:
                    # Benzersiz bir ID oluştur
                    ka_no = f"AUTO-{str(uuid.uuid4())[:8]}"
                    print(f"⚠️ Fatura numarası bulunamadı, otomatik ID oluşturuldu: {ka_no}")
            
            formatted_invoice = {
                'KANo': ka_no,
                'VergiNumarasi': invoice.get('TaxNo', ''),
                'TumMusteriAdi': invoice.get('CustomerName', ''),
                'VergiDairesi': invoice.get('TaxOffice', ''),
                'Adres': invoice.get('Address', ''),
                'Il': invoice.get('City', ''),
                'Ilce': invoice.get('District', ''),
                'KDVOrani': invoice.get('VatRate', 0),
                'KDVTutari': invoice.get('VatAmount', 0),
                'KDVsizTutar': invoice.get('NetAmount', 0),
                'KDVliToplamTutar': invoice.get('GrossAmount', 0),
                'IslemSaati': invoice.get('IslemSaati', '')
            }
            formatted_invoices.append(formatted_invoice)
        
        return formatted_invoices
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
                'TumMusteriAdi': kayit.get('TumMusteriAdi', ''),  # ERTUTECH yazısını kaldırdık
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
                'IslemSaati': kayit.get('IslemSaati', '')
            }
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
        
        tree = ET.parse('ornek.xml')
        root = tree.getroot()
        
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
        if customer is not None:
            party = customer.find('.//cac:Party', namespaces)
            if party is not None:
                # VKN/TCKN güncelleme
                id_element = party.find('.//cac:PartyIdentification/cbc:ID[@schemeID]', namespaces)
                if id_element is not None:
                    if is_earchive:
                        # E-Arşiv için TCKN olarak ayarla
                        id_element.set('schemeID', 'TCKN')
                        id_element.text = vkn
                        print(f"✅ Müşteri TCKN güncellendi: {vkn}")
                    else:
                        # E-Fatura için VKN olarak ayarla
                        id_element.set('schemeID', 'VKN')
                        id_element.text = vkn
                        print(f"✅ Müşteri VKN güncellendi: {vkn}")
                
                # Unvan güncelle
                name_element = party.find('.//cac:PartyName/cbc:Name', namespaces)
                if name_element is not None:
                    # Fatura tipine göre unvan kaynağını belirle
                    if is_earchive:
                        # E-Arşiv için JSON'dan gelen TumMusteriAdi kullan
                        if formatted_invoice_data:
                            name_element.text = formatted_invoice_data['TumMusteriAdi']
                            print(f"✅ Müşteri unvanı (E-Arşiv için JSON'dan) güncellendi: {name_element.text}")
                        else:
                            name_element.text = unvan if unvan else ""
                            print(f"✅ Müşteri unvanı (E-Arşiv için) güncellendi: {name_element.text}")
                    else:
                        # E-Fatura için TURMOB'dan gelen kimlikUnvani kullan
                        name_element.text = unvan if unvan else ""
                        print(f"✅ Müşteri unvanı (E-Fatura için TURMOB'dan) güncellendi: {name_element.text}")
                
                # Person elementini kontrol et
                person_element = party.find('.//cac:Person', namespaces)
                
                if is_earchive:
                    # E-Arşiv için Person elementini ekle veya güncelle
                    if person_element is None:
                        # Person elementi yoksa oluştur
                        person_element = ET.SubElement(party, '{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}Person')
                        ET.SubElement(person_element, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}FirstName')
                        ET.SubElement(person_element, '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}FamilyName')
                        print("✅ Person elementi oluşturuldu")
                    
                    # Ad-Soyad bölme işlemi
                    # E-Arşiv için JSON'dan gelen TumMusteriAdi kullan
                    customer_name = formatted_invoice_data['TumMusteriAdi'] if formatted_invoice_data else unvan
                    if customer_name:
                        name_parts = customer_name.split()
                        if len(name_parts) > 0:
                            last_name = name_parts[-1]  # Son kelime soyad
                            first_name = " ".join(name_parts[:-1]) if len(name_parts) > 1 else ""  # Geri kalan kısım ad
                            
                            # FirstName güncelle
                            first_name_element = person_element.find('./cbc:FirstName', namespaces)
                            if first_name_element is not None:
                                first_name_element.text = first_name
                                print(f"✅ Müşteri adı güncellendi: {first_name}")
                            
                            # FamilyName güncelle
                            family_name_element = person_element.find('./cbc:FamilyName', namespaces)
                            if family_name_element is not None:
                                family_name_element.text = last_name
                                print(f"✅ Müşteri soyadı güncellendi: {last_name}")
                else:
                    # E-Fatura için Person elementini kaldır
                    if person_element is not None:
                        party.remove(person_element)
                        print("✅ Person elementi kaldırıldı (E-Fatura için gerekli değil)")
                
                # Adres güncelle
                address_element = party.find('.//cac:PostalAddress/cbc:BuildingName', namespaces)
                if address_element is not None:
                    address_element.text = tam_adres
                    print(f"✅ Müşteri adresi güncellendi")
                
                # İlçe güncelle
                subdivision_element = party.find('.//cac:PostalAddress/cbc:CitySubdivisionName', namespaces)
                if subdivision_element is not None:
                    subdivision_element.text = ilce
                    print(f"✅ Müşteri ilçesi güncellendi: {ilce}")
                
                # İl güncelle
                city_element = party.find('.//cac:PostalAddress/cbc:CityName', namespaces)
                if city_element is not None:
                    city_element.text = il
                    print(f"✅ Müşteri ili güncellendi: {il}")
                
                # Vergi dairesi güncelle
                tax_scheme_element = party.find('.//cac:PartyTaxScheme/cac:TaxScheme/cbc:Name', namespaces)
                if tax_scheme_element is not None:
                    tax_scheme_element.text = vergi_dairesi if vergi_dairesi else ""
                    print(f"✅ Müşteri vergi dairesi güncellendi: {vergi_dairesi}")

        # Kayıt verileri varsa, fatura detaylarını güncelle
        if formatted_invoice_data:
            # Item altındaki cbc:Name elementini PlakaNo ile güncelle
            item_name_element = root.find(".//cac:Item/cbc:Name", namespaces)
            if item_name_element is not None and formatted_invoice_data['PlakaNo']:
                item_name_element.text = f"{formatted_invoice_data['PlakaNo']} PLAKALI ARAÇ KİRALAMA BEDELİ"
                print(f"✅ Plaka güncellendi: {item_name_element.text}")

            # InvoicedQuantity güncelleme (Kira günü)
            invoiced_quantity_element = root.find(".//cbc:InvoicedQuantity", namespaces)
            if invoiced_quantity_element is not None:
                invoiced_quantity_element.text = str(int(float(formatted_invoice_data['KiraGunu'])))
                print(f"✅ Kira günü güncellendi: {invoiced_quantity_element.text}")

            # PriceAmount güncelleme (Günlük fiyat)
            price_amount_element = root.find(".//cbc:PriceAmount", namespaces)
            if price_amount_element is not None:
                try:
                    price_per_day = float(formatted_invoice_data['KDVsizTutar']) / float(formatted_invoice_data['KiraGunu'])
                    price_amount_element.text = f"{price_per_day:.2f}"
                    print(f"✅ Günlük fiyat güncellendi: {price_amount_element.text}")
                except ZeroDivisionError:
                    price_amount_element.text = "0.00"
                    print("⚠️ Kira günü sıfır olduğu için günlük fiyat 0.00 olarak ayarlandı")

            # KDV Oranı güncelleme
            percent_element = root.find(".//cbc:Percent", namespaces)
            if percent_element is not None:
                percent_element.text = str(int(formatted_invoice_data['KDVOrani']))
                print(f"✅ KDV oranı güncellendi: {percent_element.text}")

            # TaxAmount güncelleme (KDV tutarı)
            tax_amount_elements = root.findall(".//cbc:TaxAmount", namespaces)
            for tax_amount_element in tax_amount_elements:
                tax_amount_element.text = f"{formatted_invoice_data['KDVTutari']:.2f}"
                print(f"✅ KDV tutarı güncellendi: {tax_amount_element.text}")

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
                        element.text = str(formatted_invoice_data['KDVsizTutar'])
                        print(f"✅ KDVsiz tutar güncellendi ({xpath}): {element.text}")

            # KDVli tutar ile güncellenecek elementler
            elements_to_update_kdvli = [
                ".//cbc:TaxInclusiveAmount",
                ".//cbc:PayableAmount"
            ]

            for xpath in elements_to_update_kdvli:
                element = root.find(xpath, namespaces)
                if element is not None:
                    element.text = str(formatted_invoice_data['KDVliToplamTutar'])
                    print(f"✅ KDVli tutar güncellendi ({xpath}): {element.text}")

            # Toplam tutarı yazıya çevir
            toplam_tutar = float(formatted_invoice_data['KDVliToplamTutar'])
            tutar_yazi = sayi_to_yazi(toplam_tutar)

            # Note elementlerini güncelle
            note_elements = root.findall(".//cbc:Note", namespaces)
            if note_elements and len(note_elements) >= 2:
                note_elements[0].text = f"Yazı ile: # {tutar_yazi} #"
                note_elements[1].text = f"KA: {formatted_invoice_data['KANo']}"
                print(f"✅ Note elementleri güncellendi")

        # Güncellenmiş XML'i kaydet
        updated_xml_path = 'updated_invoice.xml'
        tree.write(updated_xml_path, encoding='UTF-8', xml_declaration=True)
        print(f"✅ Güncellenmiş XML kaydedildi: {updated_xml_path}")
        
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
def save_processed_invoice(ka_no):
    try:
        processed_data = load_processed_invoices()
        
        # KA numarası zaten işlenmişse ekleme
        if ka_no not in processed_data["processed_invoices"]:
            processed_data["processed_invoices"].append(ka_no)
        
        # Son kontrol zamanını güncelle
        processed_data["last_check_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with open(PROCESSED_INVOICES_FILE, 'w', encoding='utf-8') as f:
            json.dump(processed_data, indent=2, ensure_ascii=False, fp=f)
        
        print(f"✅ KA No: {ka_no} işlenmiş faturalar listesine eklendi")
        return True
    except Exception as e:
        print(f"❌ İşlenmiş fatura kaydedilirken hata: {str(e)}")
        return False

def process_new_invoices():
    try:
        # Önce işlenmiş faturaları yükle
        processed_data = load_processed_invoices()
        processed_invoices = processed_data["processed_invoices"]
        
        # Otokoc API'den fatura verilerini çek
        invoice_data = get_invoice_data()
        
        if not invoice_data:
            print("⚠️ İşlenecek fatura verisi bulunamadı")
            return
        
        # İşlenmemiş faturaları filtrele
        unprocessed_invoices = []
        for kayit in invoice_data:
            ka_no = kayit.get('KANo', '')
            if ka_no and ka_no not in processed_invoices:
                unprocessed_invoices.append(kayit)
                print(f"✅ İşlenecek yeni fatura: KA No: {ka_no}")
            elif ka_no in processed_invoices:
                print(f"⏭️ Fatura zaten işlenmiş: KA No: {ka_no}")
            else:
                print(f"⚠️ KA No bulunamadı, fatura atlanıyor")
        
        if not unprocessed_invoices:
            print(f"\n✅ İşlenecek yeni fatura bulunamadı. Toplam işlenmiş fatura: {len(processed_invoices)}")
            return
        
        # Yeni faturalar varsa EDM'ye bağlan
        print(f"\n📋 Toplam {len(unprocessed_invoices)} yeni kayıt işlenecek")
        
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

<b>Toplam İşlenecek Kayıt:</b> {len(unprocessed_invoices)}
<b>Başlangıç Tarihi:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
"""
        send_telegram_notification(start_notification)
        
        # Başarılı ve başarısız işlem sayaçları
        success_count = 0
        fail_count = 0

        # Her kayıt için işlem yap
        for index, kayit in enumerate(unprocessed_invoices, 1):
            vkn = kayit.get('VergiNumarasi')  # VergiNumarasi alanını kullan
            ka_no = kayit.get('KANo', 'Bilinmiyor')
            
            print(f"\n{'='*50}")
            print(f"🔄 Kayıt {index}/{len(unprocessed_invoices)} işleniyor")
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
                # API'den gelen bilgileri kullan
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

            # TURMOB'dan gelen adres bilgileri null ise API'den gelen bilgileri kullan
            if not tam_adres or not il or not ilce:
                print("\n⚠️ Adres bilgileri eksik, API'den gelen bilgiler kullanılıyor")
                tam_adres = kayit.get('Adres', '')
                il = kayit.get('Il', '')
                ilce = kayit.get('Ilce', '')

            # XML güncelle ve faturayı yükle - kayıt verisini de gönder
            if update_xml_and_load(client, session_id, vkn, alias, vergi_dairesi, unvan, tam_adres, il, ilce, kayit):
                print(f"\n✅ VKN: {vkn}, KA No: {ka_no} - İşlem başarıyla tamamlandı")
                success_count += 1
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
🔹 <b>Toplam İşlenen Kayıt:</b> {len(unprocessed_invoices)}
🔹 <b>Başarılı İşlem:</b> {success_count}
🔹 <b>Başarısız İşlem:</b> {fail_count}
🔹 <b>Toplam İşlenmiş Fatura:</b> {len(processed_data["processed_invoices"]) + success_count}

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
        
        # Başlangıçta IP bilgilerini göster
        ip_info = get_my_ip()
        if ip_info:
            print(f"\n📡 Sistem IP Bilgileri:")
            print(f"   🌐 Dış IP: {ip_info['external_ip']}")
            print(f"   🏠 Yerel IP: {ip_info['local_ip']}")
            print(f"   💻 Hostname: {ip_info['hostname']}")
        
        send_telegram_notification("<b>🚀 Fatura İşleme Servisi Başlatıldı</b>")
        
        # İlk token'ı al
        if not get_otokoc_token():
            print("❌ Otokoc API token alınamadı, servis başlatılamıyor")
            send_telegram_notification("<b>❌ Otokoc API token alınamadı, servis başlatılamıyor</b>")
            return
        
        # İlk çalıştırmada tüm faturaları işle
        process_new_invoices()
        
        # Her 1 dakikada bir yeni faturaları kontrol et
        while True:
            print(f"\n⏳ Bir sonraki kontrol için bekleniyor... ({datetime.now().strftime('%H:%M:%S')})")
            time.sleep(60)  # 60 saniye bekle
            print(f"\n🔍 Yeni faturalar kontrol ediliyor... ({datetime.now().strftime('%H:%M:%S')})")
            
            # Token kontrolü
            check_and_refresh_token()
            
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

if __name__ == "__main__":
    main()