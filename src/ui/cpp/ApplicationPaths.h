#pragma once
#include <QDir>
#include <QString>

// Bootstrap location only. Python owns the data layout below this root.
namespace ApplicationPaths
{
QString dataDirectory(const QDir& project);
}
