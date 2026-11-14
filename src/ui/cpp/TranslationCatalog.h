#pragma once
#include <QJsonObject>
#include <QTranslator>
#include <QVariantList>

// Shared JSON catalogs serve Qt's qsTr()/tr() and the Python bridge.
// Source strings are French; absent translations fall back to the source.
class TranslationCatalog final : public QTranslator
{
  public:
    explicit TranslationCatalog(QObject* parent = nullptr);
    ~TranslationCatalog() override;
    bool setLanguage(const QString& language);

    QString language() const
    {
        return m_language;
    }

    QString text(const QString& source) const;

    QVariantList languages() const
    {
        return m_languages;
    }

    bool isEmpty() const override
    {
        return false;
    }

    QString translate(const char* context, const char* sourceText,
                      const char* disambiguation = nullptr, int n = -1) const override;

  private:
    QString m_language = "fr";
    QJsonObject m_messages;
    QList<QPair<QString, QString>> m_prefixes;
    QHash<QString, QString> m_sources;
    QVariantList m_languages;
};
