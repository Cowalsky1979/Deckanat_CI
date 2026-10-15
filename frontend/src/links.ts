// Ссылки между страницами, которые нужны нескольким компонентам.

// загрузка исправленной версии документа: тип подставляется, заявка уйдёт в деканат сама
export const revisionLink = (doc: { id: string; doc_type: string }) => `/?parent=${doc.id}&type=${doc.doc_type}#upload`
