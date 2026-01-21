# Sera Durumu Analizi - {{timestamp}}

## MEVCUT VERİLER

### Sensörler
| Parametre | Değer | Durum | Trend |
|-----------|-------|-------|-------|
| Sıcaklık | {{temperature}}°C | {{temp_status}} | {{temp_trend}} |
| Nem | {{humidity}}% | {{hum_status}} | {{hum_trend}} |
| Toprak Nemi | {{soil_moisture}}% | {{soil_status}} | {{soil_trend}} |
| Işık | {{light}} lux | {{light_status}} | - |

### Hava Tahmini
- Bugün: {{today_high}}°C / {{today_low}}°C - {{today_conditions}}
- Yarın: {{tomorrow_high}}°C / {{tomorrow_low}}°C - {{tomorrow_conditions}}
- Yağmur olasılığı: {{rain_probability}}%

### Cihaz Durumları
- Pompa: {{pump_state}} (bugün toplam: {{pump_today_minutes}} dk)
- Fan: {{fan_state}} (bugün toplam: {{fan_today_minutes}} dk)

## ANALİZ

### Endişeler
{{concerns}}

### Olumlu Noktalar
{{positives}}

## KARAR

**Aksiyon**: {{action}}
**Sebep**: {{reason}}
**Güven**: {{confidence}}%

## SONRAKI ADIM

{{next_check_minutes}} dakika sonra tekrar kontrol et.
İzle: {{watch_for}}
