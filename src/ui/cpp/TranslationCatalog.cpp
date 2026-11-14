#include "TranslationCatalog.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QRegularExpression>
#include <algorithm>

TranslationCatalog::TranslationCatalog(QObject* parent) : QTranslator(parent)
{
    Q_INIT_RESOURCE(translations);
    QFile english(":/i18n/en.json");
    QJsonObject englishMessages;
    if (english.open(QIODevice::ReadOnly))
    {
        englishMessages =
            QJsonDocument::fromJson(english.readAll()).object().value("messages").toObject();
    }
    for (auto it = englishMessages.begin(); it != englishMessages.end(); ++it)
    {
        m_sources.insert(it.value().toString(), it.key());
    }
    const QDir directory(":/i18n");
    for (const auto& name : directory.entryList({"*.json"}, QDir::Files, QDir::Name))
    {
        QFile catalog(directory.filePath(name));
        if (catalog.open(QIODevice::ReadOnly))
        {
            const auto metadata = QJsonDocument::fromJson(catalog.readAll()).object();
            if (metadata.contains("language") && metadata.contains("name"))
            {
                m_languages.append(QVariantMap{{"code", metadata.value("language").toString()},
                                               {"name", metadata.value("name").toString()}});
            }
        }
    }
    QCoreApplication::installTranslator(this);
}

TranslationCatalog::~TranslationCatalog()
{
    QCoreApplication::removeTranslator(this);
}

bool TranslationCatalog::setLanguage(const QString& language)
{
    static const QRegularExpression code("^[a-z]{2}(?:-[A-Z]{2})?$");
    if (!code.match(language).hasMatch())
    {
        return false;
    }
    QFile file(":/i18n/" + language + ".json");
    if (!file.open(QIODevice::ReadOnly))
    {
        return false;
    }
    const auto document = QJsonDocument::fromJson(file.readAll());
    if (!document.isObject() || !document.object().value("messages").isObject())
    {
        return false;
    }
    m_messages = document.object().value("messages").toObject();
    m_language = language;
    m_prefixes.clear();
    for (auto it = m_messages.begin(); it != m_messages.end(); ++it)
    {
        m_sources.insert(it.value().toString(), it.key());
        if (it.key().endsWith(": "))
        {
            m_prefixes.append({it.key(), it.value().toString()});
        }
    }
    std::sort(m_prefixes.begin(), m_prefixes.end(),
              [](const auto& left, const auto& right)
              {
                  return left.first.size() > right.first.size();
              });
    return true;
}

QString TranslationCatalog::text(const QString& value) const
{
    const auto source = m_sources.value(value, value);
    if (m_messages.contains(source))
    {
        return m_messages.value(source).toString(source);
    }
    // Only translate registered message prefixes, never arbitrary substrings
    // inside file paths, archive names, user descriptions or technical logs.
    for (const auto& [prefix, translation] : m_prefixes)
    {
        if (source.startsWith(prefix))
        {
            return translation + source.mid(prefix.size());
        }
    }
    return source;
}

QString TranslationCatalog::translate(const char*, const char* sourceText, const char*, int) const
{
    const auto source = QString::fromUtf8(sourceText);
    return m_messages.contains(source) ? m_messages.value(source).toString() : QString();
}
