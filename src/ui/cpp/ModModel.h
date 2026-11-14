#pragma once
#include <QAbstractListModel>
#include <QVariantMap>

// Stable IDs belong to the domain, never to a delegate's visible index.
class ModModel final : public QAbstractListModel
{
    Q_OBJECT
    Q_PROPERTY(int count READ rowCount NOTIFY countChanged)
  public:
    enum Role
    {
        ModRole = Qt::UserRole + 1
    };

    explicit ModModel(QObject* parent = nullptr) : QAbstractListModel(parent) {}

    int rowCount(const QModelIndex& parent = {}) const override;
    QVariant data(const QModelIndex& index, int role) const override;

    QHash<int, QByteArray> roleNames() const override
    {
        return {{ModRole, "mod"}};
    }

    void setRows(const QVariantList& rows);
    void setFilter(QString query);
    Q_INVOKABLE QVariantMap get(int index) const;
    QVariantMap find(const QString& id) const;
  signals:
    void countChanged();

  private:
    void refilter();
    QVariantList m_rows, m_visible;
    QString m_filter;
};
