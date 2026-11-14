#include "ModModel.h"

int ModModel::rowCount(const QModelIndex& parent) const
{
    return parent.isValid() ? 0 : int(m_visible.size());
}

QVariant ModModel::data(const QModelIndex& index, int role) const
{
    return role == ModRole && index.isValid() && index.row() >= 0 && index.row() < m_visible.size()
               ? m_visible[index.row()]
               : QVariant{};
}

void ModModel::setRows(const QVariantList& rows)
{
    if (m_rows == rows)
    {
        return;
    }
    m_rows = rows;
    refilter();
}

void ModModel::setFilter(QString query)
{
    query = query.trimmed().toCaseFolded();
    if (query == m_filter)
    {
        return;
    }
    m_filter = query;
    refilter();
}

void ModModel::refilter()
{
    beginResetModel();
    m_visible.clear();
    for (const auto& row : m_rows)
    {
        const auto item = row.toMap();
        if (m_filter.isEmpty() ||
            (item.value("name").toString() + " " + item.value("title").toString())
                .toCaseFolded()
                .contains(m_filter))
        {
            m_visible.append(row);
        }
    }
    endResetModel();
    emit countChanged();
}

QVariantMap ModModel::get(int index) const
{
    return index >= 0 && index < m_visible.size() ? m_visible[index].toMap() : QVariantMap{};
}

QVariantMap ModModel::find(const QString& id) const
{
    for (const auto& row : m_rows)
    {
        if (row.toMap().value("id").toString() == id)
        {
            return row.toMap();
        }
    }
    return {};
}
