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
- [ ] **Çoklu Dil (i18n):** Eklenen/değiştirilen tüm kullanıcı metinleri hem Türkçe (`tr`) hem İngilizce (`en`) olarak `sourcedock/i18n.py` dosyasına eklendi.
- [ ] **Testler:** `python3 tools/run_tests.py` çalıştırıldı; GTK için Xvfb/Openbox kullanıldı, başarısız ve atlanan testler belirtildi (bkz. `tests/README.md`).
- [ ] **Paketleme:** Gerekliyse `./packaging/build_deb.sh` ile `.deb` inşası denendi.
- [ ] **GUI:** Ana pencere, TR/EN, açık/koyu tema ve dar pencerede ilgili akış doğrulandı.
- [ ] **Yetki:** Paket kurma/silme testleri gerçek host sistemi değiştirmeyen fake runner kullanıyor.
- [ ] **Kanıt:** Dağıtım, Python/GTK sürümü ve çalıştırılan kontroller belirtildi; hassas log bilgileri maskelendi.

