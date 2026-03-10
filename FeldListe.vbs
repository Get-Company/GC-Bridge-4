Option Explicit

Dim FSO
Set FSO = WScript.CreateObject("Scripting.FileSystemObject")

Dim TextFile
Set TextFile = FSO.CreateTextFile("D:\htdocs\com\FeldListe.VB\FELD_25.LST",true,false)

Dim BpNT
Set BpNT = WScript.CreateObject("BpNT.Application")

Call BpNT.Init ("Egon Heimann GmbH","","f.buchner", "")
Call BpNT.SelectMand ("58")

Sub DoDataSet(aSpaces,aDataSetInfo,aName)
  Dim FieldInfo
  Dim Index
  Dim IndexField
  Dim NestedDataSet
  Dim Access

  TextFile.WriteLine(aSpaces & aName & aDataSetInfo.Name & " - " & aDataSetInfo.Bez)
  For Each FieldInfo in aDataSetInfo.Fields
    if FieldInfo.CanAccess then
      Access = " +"
    else
      Access = " /"
    End If
    If FieldInfo.IsCalcField Then
      TextFile.WriteLine(aSpaces & "  Field: *" & FieldInfo.Name & " - " & FieldInfo.Info & " (" & FieldInfo.FieldType & ")" & Access)
    Else
      TextFile.WriteLine(aSpaces & "  Field: " & FieldInfo.Name & " - " & FieldInfo.Info & " (" & FieldInfo.FieldType & ")" & Access)
    End If
  Next
  For Each Index in aDataSetInfo.Indices
    TextFile.WriteLine(aSpaces & "  Index: " & Index.Name & " - " & Index.Info)
    For Each IndexField in Index.IndexFields
      TextFile.WriteLine(aSpaces & "    IndexField:" & IndexField.Name & " - " & IndexField.Info)
    Next
  Next
  For Each NestedDataSet in aDataSetInfo.NestedDataSets
    call DoDataSet("  " & aSpaces,NestedDataSet, "NestedDataSet: ")
  Next
End Sub

Dim DataSetInfo

For Each DataSetInfo in BpNT.DataSetInfos
  call DoDataSet("",DataSetInfo,"DataSet: ")
  TextFile.WriteLine("")
Next

TextFile.Close

MsgBox ("Fertig!")