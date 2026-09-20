from xml.etree import ElementTree
from config import readconfig
import os


activity={}
class Element():
    def __init__(self, activity_name, element_name):
        self.activity = activity_name
        self.element = element_name
        element_dict = get_el_dict(self.activity, self.element)
        self.pathType = element_dict.get('pathType')
        self.pathValue = element_dict.get('pathValue')


def getpathType(activity,element):
    element_dict = get_el_dict(activity,element)
    pathType = element_dict.get('pathType')
    pathValue = element_dict.get('pathValue')


def set_xml():
    """
    get element
    :return:
    """


    if len(activity) == 0:
        proDir=readconfig.read('filepath','datapath')
        filepath = os.path.join(proDir, 'element.xml')

        tree = ElementTree.parse(filepath)
        for a in tree.findall('activity'):
            activity_name = a.get('name')
            element = {}
            # getchildren() 自 Python 3.9 起已移除，改为直接迭代子元素
            for e in list(a):
                element_name = e.get('id')

                element_child = {}
                for t in list(e):

                    element_child[t.tag] = t.text
                element[element_name] = element_child
            activity[activity_name] = element

def get_el_dict(activity_name, element):
    set_xml()

    element_dict = activity.get(activity_name).get(element)

    return element_dict

if __name__ == '__main__':

    pass