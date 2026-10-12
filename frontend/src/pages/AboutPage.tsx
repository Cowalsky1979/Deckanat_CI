import { useQuery } from '@tanstack/react-query'
import { api } from '../api'

export default function AboutPage() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health })
  return (
    <div className="max-w-4xl">
      <h1 className="section-title">О сервисе</h1>
      <div className="mt-7 card p-6 sm:p-8 space-y-4 text-[15px] leading-7">
      <p>
        «Онлайн-деканат» — цифровой секретарь для студента: читает фото или скан документа, раскладывает данные по полям,
        выполняет предварительную проверку комплектности по Положению и отвечает на вопросы со ссылками на поля документа
        и пункты Положения.
      </p>
      <h2 className="font-semibold text-lg text-ink-900">Конвейер</h2>
      <ol className="list-decimal pl-5 space-y-1">
        <li>Загрузка JPG/PNG/PDF, предобработка «плохих снимков»: перспектива, наклон до 30°, тени, блики, апскейл.</li>
        <li>OCR: PaddleOCR (PP-OCRv5, кириллическая модель) + Tesseract 5 как резерв. Всё локально.</li>
        <li>Извлечение полей по конфигу типа (YAML), нормализация дат в ГГГГ-ММ-ДД, ФИО, номеров.</li>
        <li>Детекция подписи и печати как графических элементов (надпись «М.П.» отметкой не считается, п. 2.3).</li>
        <li>Проверка комплектности и ответы по правилам Положения — детерминированно, без языковых моделей.</li>
      </ol>
      <h2 className="font-semibold text-lg text-ink-900">Ограничения</h2>
      <ul className="list-disc pl-5 space-y-1">
        <li>Сервис не принимает документы и не оформляет отпуск, перевод или зачёт — решение за сотрудником деканата (п. 1.3).</li>
        <li>Проверяется наличие сведений и отметок, а не их подлинность или юридическая сила (п. 2.6).</li>
        <li>Если ответа нет в документе и Положении, сервис сообщает об этом и рекомендует обратиться в деканат (п. 2.4).</li>
        <li>Поддерживается одна страница; многостраничные PDF, рукописный текст — вне обязательной версии 1.0.</li>
      </ul>
      <h2 className="font-semibold text-lg text-ink-900">Состояние</h2>
      <div className="text-ink-600">
        {health.data ? (
          <>API: {health.data.status}; движки OCR: {Object.entries(health.data.engines).map(([k, v]) => `${k} — ${v}`).join(', ')}</>
        ) : (
          'проверка…'
        )}
      </div>
      <p className="text-xs text-ink-500">Интерфейс также доступен в Telegram-боте — тот же бэкенд, без OCR на стороне бота.</p>
      </div>
    </div>
  )
}
