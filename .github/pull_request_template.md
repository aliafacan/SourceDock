## ⚡ Pull Request Özeti

### Yapılan Değişiklikler
- [ ] Yeni özellik: ...
- [ ] Hata düzeltmesi: ...
- [ ] Dokümantasyon / Test: ...
- [ ] Refactoring / Temizlik: ...

### Açıklama & Motivasyon
Bu PR'ın amacı, çözdüğü problem ve tasarım kararları:

### Kontrol Listesi (Checklist)
- [ ] **Modüler Mimari Kuralı:** Kodlar tek bir dev dosyaya yığılmadı, uygun alt modüle (`core/`, `backend/`, `ui/views/`, `ui/components/`) yerleştirildi.
- [ ] **Çoklu Dil (i18n):** Eklenen/değiştirilen tüm kullanıcı metinleri hem Türkçe (`tr`) hem İngilizce (`en`) olarak `voltapp/i18n.py` dosyasına eklendi.
- [ ] **Testler:** `python3 -m unittest discover -s tests -v` komutu çalıştırıldı ve tüm birim testleri başarıyla geçti.
- [ ] **Paketleme:** Gerekliyse `./packaging/build_deb.sh` ile `.deb` inşası denendi.
