/****************************************************************************
** Meta object code from reading C++ file 'ascii2edf.h'
**
** Created by: The Qt Meta Object Compiler version 68 (Qt 6.8.2)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../cnvs/ascii2edf.h"
#include <QtGui/qtextcursor.h>
#include <QtGui/qscreen.h>
#include <QtNetwork/QSslError>
#include <QtCore/qmetatype.h>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'ascii2edf.h' doesn't include <QObject>."
#elif Q_MOC_OUTPUT_REVISION != 68
#error "This file was generated using the moc from 6.8.2. It"
#error "cannot be used with the include files from this version of Qt."
#error "(The moc has changed too much.)"
#endif

#ifndef Q_CONSTINIT
#define Q_CONSTINIT
#endif

QT_WARNING_PUSH
QT_WARNING_DISABLE_DEPRECATED
QT_WARNING_DISABLE_GCC("-Wuseless-cast")
namespace {
struct qt_meta_tag_ZN15UI_ASCII2EDFappE_t {};
} // unnamed namespace


#ifdef QT_MOC_HAS_STRINGDATA
static constexpr auto qt_meta_stringdata_ZN15UI_ASCII2EDFappE = QtMocHelpers::stringData(
    "UI_ASCII2EDFapp",
    "numofcolumnschanged",
    "",
    "gobuttonpressed",
    "savebuttonpressed",
    "loadbuttonpressed",
    "helpbuttonpressed",
    "setallbuttonpressed",
    "setallcheckedbuttonpressed",
    "setalluncheckedbuttonpressed",
    "autoPhysicalMaximumCheckboxChanged",
    "signalCheckboxChanged"
);
#else  // !QT_MOC_HAS_STRINGDATA
#error "qtmochelpers.h not found or too old."
#endif // !QT_MOC_HAS_STRINGDATA

Q_CONSTINIT static const uint qt_meta_data_ZN15UI_ASCII2EDFappE[] = {

 // content:
      12,       // revision
       0,       // classname
       0,    0, // classinfo
      10,   14, // methods
       0,    0, // properties
       0,    0, // enums/sets
       0,    0, // constructors
       0,       // flags
       0,       // signalCount

 // slots: name, argc, parameters, tag, flags, initial metatype offsets
       1,    1,   74,    2, 0x08,    1 /* Private */,
       3,    0,   77,    2, 0x08,    3 /* Private */,
       4,    0,   78,    2, 0x08,    4 /* Private */,
       5,    0,   79,    2, 0x08,    5 /* Private */,
       6,    0,   80,    2, 0x08,    6 /* Private */,
       7,    0,   81,    2, 0x08,    7 /* Private */,
       8,    0,   82,    2, 0x08,    8 /* Private */,
       9,    0,   83,    2, 0x08,    9 /* Private */,
      10,    1,   84,    2, 0x08,   10 /* Private */,
      11,    1,   87,    2, 0x08,   12 /* Private */,

 // slots: parameters
    QMetaType::Void, QMetaType::Int,    2,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void, QMetaType::Int,    2,
    QMetaType::Void, QMetaType::Int,    2,

       0        // eod
};

Q_CONSTINIT const QMetaObject UI_ASCII2EDFapp::staticMetaObject = { {
    QMetaObject::SuperData::link<QObject::staticMetaObject>(),
    qt_meta_stringdata_ZN15UI_ASCII2EDFappE.offsetsAndSizes,
    qt_meta_data_ZN15UI_ASCII2EDFappE,
    qt_static_metacall,
    nullptr,
    qt_incomplete_metaTypeArray<qt_meta_tag_ZN15UI_ASCII2EDFappE_t,
        // Q_OBJECT / Q_GADGET
        QtPrivate::TypeAndForceComplete<UI_ASCII2EDFapp, std::true_type>,
        // method 'numofcolumnschanged'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        QtPrivate::TypeAndForceComplete<int, std::false_type>,
        // method 'gobuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'savebuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'loadbuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'helpbuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'setallbuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'setallcheckedbuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'setalluncheckedbuttonpressed'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        // method 'autoPhysicalMaximumCheckboxChanged'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        QtPrivate::TypeAndForceComplete<int, std::false_type>,
        // method 'signalCheckboxChanged'
        QtPrivate::TypeAndForceComplete<void, std::false_type>,
        QtPrivate::TypeAndForceComplete<int, std::false_type>
    >,
    nullptr
} };

void UI_ASCII2EDFapp::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<UI_ASCII2EDFapp *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->numofcolumnschanged((*reinterpret_cast< std::add_pointer_t<int>>(_a[1]))); break;
        case 1: _t->gobuttonpressed(); break;
        case 2: _t->savebuttonpressed(); break;
        case 3: _t->loadbuttonpressed(); break;
        case 4: _t->helpbuttonpressed(); break;
        case 5: _t->setallbuttonpressed(); break;
        case 6: _t->setallcheckedbuttonpressed(); break;
        case 7: _t->setalluncheckedbuttonpressed(); break;
        case 8: _t->autoPhysicalMaximumCheckboxChanged((*reinterpret_cast< std::add_pointer_t<int>>(_a[1]))); break;
        case 9: _t->signalCheckboxChanged((*reinterpret_cast< std::add_pointer_t<int>>(_a[1]))); break;
        default: ;
        }
    }
}

const QMetaObject *UI_ASCII2EDFapp::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *UI_ASCII2EDFapp::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_meta_stringdata_ZN15UI_ASCII2EDFappE.stringdata0))
        return static_cast<void*>(this);
    return QObject::qt_metacast(_clname);
}

int UI_ASCII2EDFapp::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 10)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 10;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 10)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 10;
    }
    return _id;
}
QT_WARNING_POP
