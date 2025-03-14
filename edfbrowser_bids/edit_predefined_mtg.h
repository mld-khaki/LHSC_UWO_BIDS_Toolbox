/*
***************************************************************************
*
* Author: Teunis van Beelen
*
* Copyright (C) 2010 - 2024 Teunis van Beelen
*
* Email: teuniz@protonmail.com
*
***************************************************************************
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation, version 3 of the License.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License
* along with this program.  If not, see <http://www.gnu.org/licenses/>.
*
***************************************************************************
*/




#ifndef EDITPREDEFINEDMTGFORM1_H
#define EDITPREDEFINEDMTGFORM1_H



#include "qt_headers.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "global.h"
#include "mainwindow.h"
#include "utils.h"



class UI_Mainwindow;



class UI_edit_predefined_mtg_window : public QObject
{
  Q_OBJECT

public:
  UI_edit_predefined_mtg_window(QWidget *parent);

  UI_Mainwindow *mainwindow;

private:

  QDialog      *edit_predefined_mtg_Dialog,
               *dialog;

  QListWidget  *mtg_path_list;

  QPushButton  *CloseButton,
               *button1,
               *button2,
               *button3;

  QListWidgetItem *listItem;

  int row;


private slots:

void rowClicked(QListWidgetItem *);
void adEntry();
void removeEntry();

};



#endif


