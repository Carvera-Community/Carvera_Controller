#this is for 4 axis now

#import os
#os.environ['KIVY_GL_BACKEND'] = 'sdl2'

import sys
from kivy.app import App
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.graphics.instructions import RenderContext
from kivy.graphics.transformation import Matrix
from kivy.graphics import *
from kivy.graphics.opengl import *
from kivy.clock import Clock
from kivy.utils import platform
import os
from math import *

import datetime
start_time = 0
def get_elapsed(str):
    global start_time
    if str == "start":
        start_time = datetime.datetime.now()
    end_time = datetime.datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    start_time = end_time
    print(f"{str} -> {elapsed_time}")

from .Objloader import ObjFile
#arc camera
import math
from .arcball_from_cpp import *
#input
from kivy.input.provider import MotionEventProvider
from kivy.input.factory import MotionEventFactory
from kivy.input.motionevent import MotionEvent

#calculate the 3d distance
def len_3d(pos1,pos2):
    return math.sqrt((pos1[0] - pos2[0])*(pos1[0] - pos2[0])+(pos1[1]-pos2[1])*(pos1[1]-pos2[1])+(pos1[2]-pos2[2])*(pos1[2]-pos2[2]))

def len_2d(pos1,pos2):
    return math.sqrt((pos1[0] - pos2[0])*(pos1[0] - pos2[0])+(pos1[1]-pos2[1])*(pos1[1]-pos2[1]))

def normalize(dir):
    length = len_3d(dir,[0,0,0])
    if(length < 0.0001):
        print('normalize failed')
        return [1,0,0]
    inv_length = 1.0 / length
    return [dir[0]*inv_length,dir[1]*inv_length,dir[2]*inv_length]

def normalize_angle(angle):
    while (angle < 0): angle += 360
    while (angle > 360): angle -= 360
    return angle
#
ZOOMSTEP = 1.1
M_PI = 3.141592653
#binary search left key
def binary_find_left(array,key):
    length=len(array)
    ans=length
    l=0
    r=length-1
    while(l<=r):
        mid=(l+r)>>1
        if(array[mid]>=key):
            ans=mid
            r=mid-1
        else: l=mid+1
    return ans-1

#rotate point around axis & angle
#https://stackoverflow.com/questions/6721544/circular-rotation-around-an-arbitrary-axis
#https://kivy.org/doc/stable/api-kivy.graphics.transformation.html
def rotate_pt_by_x_axis_angle(pt_x,pt_y,pt_z,angle_in_degree):
    axis = [1,0,0]
    mat_rot_x = Matrix()
    angle_in_radian = angle_in_degree * 3.1415926 / 180.0
    mat_rot_x.rotate(angle_in_radian,axis[0],axis[1],axis[2])
    rot_pt = mat_rot_x.transform_point(pt_x,pt_y,pt_z)
    return rot_pt
def rotate_mat_by_x_axis_angle(angle_in_degree):
    axis = [1,0,0]
    mat_rot_x = Matrix()
    angle_in_radian = angle_in_degree * 3.1415926 / 180.0
    mat_rot_x.rotate(angle_in_radian,axis[0],axis[1],axis[2])
    return mat_rot_x


#####function
def vec3_add(v1, v2):
    return [v1[0] + v2[0], v1[1] + v2[1], v1[2] + v2[2]]


def vec3_sub(v1, v2):
    return [v1[0] - v2[0], v1[1] - v2[1], v1[2] - v2[2]]


def vec3_mul_float(v1, f):
    return [v1[0] * f, v1[1] * f, v1[2] * f]


def vec3_divide(v1, ff):
    f = 1.0 / ff
    return [v1[0] * f, v1[1] * f, v1[2] * f]


def vec3_len(v1):
    return sqrt(v1[0] * v1[0] + v1[1] * v1[1] + v1[2] * v1[2])


def vec3_max(v1, v2):
    return [max(v1[0], v2[0]), max(v1[1], v2[1]), max(v1[2], v2[2])]


def vec3_min(v1, v2):
    return [min(v1[0], v2[0]), min(v1[1], v2[1]), min(v1[2], v2[2])]


def vec3_distance(v1, v2):
    v3 = vec3_sub(v1, v2)
    return vec3_len(v3)


class MyMeshManager():

    def __init__(self):

        ##data container

        # all pts
        self.positions = []
        # all lengths
        self.lengths = []
        # vertex type
        self.vertex_types = []
        # raw numbers
        self.raw_linenumbers = []
        # angles of vertices [4 axis]
        self.angles_of_vertices = []

        # mesh container
        self.meshes = []

        # vertices
        self.vertices = []
        ##  bounding area

        # record the max size of area
        self.area_size = 0.0
        # max pt
        self.max_pt = [0, 0, 0]
        # cetner of meshes
        self.area_center_sum = [0, 0, 0]
        self.area_center_sum_index = 0
        self.position_scale = 1.0 #same to scale_invert

        ## attributes
        self.is_4_axis = None

    def clear(self):
        self.positions.clear()
        # all lengths
        self.lengths.clear()
        # vertex type
        self.vertex_types.clear()
        # raw numbers
        self.raw_linenumbers.clear()
        # angles of vertices [4 axis]
        self.angles_of_vertices.clear()
        # mesh container
        self.meshes.clear()
        # vertices
        self.vertices.clear()

        #move to origin
        self.area_size = 0.0
        self.max_pt = [0, 0, 0]
        self.area_center_sum = [0,0,0]
        self.area_center_sum_index = 0
        self.position_scale = 1.0  # same to scale_invert
        self.is_4_axis = None

    def get_pt_count(self):
        return len(self.positions)

    def map_color(self, color_str):
        if color_str == 'Green':
            return [0., 1., 0.]
        elif color_str == 'Red':
            return [1., 0., 0.]
        return [1., 1., 1.]

    # get center of meshes
    def get_center(self):
        if self.area_center_sum_index == 0:
            return [0, 0, 0]

        return vec3_divide(self.area_center_sum, self.area_center_sum_index)

    def get_center_of_view(self):
        return vec3_mul_float(self.get_center(), self.position_scale)

    def get_vertex_position(self,idx):
        return [self.vertices[idx*10],self.vertices[idx*10+1],self.vertices[idx*10+2]]
    # parse single line
    def parse_line(self, line):
        arr_pt = line.split(' ')

        # position
        pos = [float(arr_pt[1]), float(arr_pt[3]), float(arr_pt[5])]
        if self.is_4_axis:
            angle = float(arr_pt[7])
            pos = rotate_pt_by_x_axis_angle(pos[0], pos[1], pos[2], angle)

        self.positions.append(pos[0])
        self.positions.append(pos[1])
        self.positions.append(pos[2])
        self.max_pt = vec3_max(self.max_pt, pos)

        # for center calculating
        self.area_center_sum = vec3_add(self.area_center_sum, pos)
        self.area_center_sum_index += 1

        # get attributes of this point
        vertex = [0] * 10
        if self.is_4_axis:
            # 1 position
            vertex[0] = pos[0]
            vertex[1] = pos[1]
            vertex[2] = pos[2]

            #angle
            angle = float(arr_pt[7])

            # 2 color
            color = self.map_color(arr_pt[9])
            vertex[3] = color[0]
            vertex[4] = color[1]
            vertex[5] = color[2]

            # 3 line number in gcode
            vertex[6] = float(arr_pt[11])


            # 4 type id
            vertex[7] = len(self.positions) - 1

            # 5 distance attribute
            vertex[8] = 0  # set after length is calculated

            # 6 set tool knife id
            vertex[9] = float(arr_pt[13])

            # push this vertex to container
            self.vertices.extend(vertex)
            self.vertex_types.append(1.0 if arr_pt[9] == "Green" else 2.0)  # line type[red | green]
            self.raw_linenumbers.append(vertex[6])
            self.angles_of_vertices.append(angle)
        else:
            # 1 position
            vertex[0] = pos[0]
            vertex[1] = pos[1]
            vertex[2] = pos[2]

            # 2 color
            color = self.map_color(arr_pt[7])
            vertex[3] = color[0]
            vertex[4] = color[1]
            vertex[5] = color[2]

            # 3 line number in gcode
            vertex[6] = float(arr_pt[9])

            # 4 type id
            vertex[7] = len(self.positions) - 1

            # 5 distance attribute
            vertex[8] = 0  # set after length is calculated

            # 6 set tool knife id
            vertex[9] = float(arr_pt[11])

            # push this vertex to container
            self.vertices.extend(vertex)

            self.vertex_types.append(1.0 if arr_pt[7] == "Green" else 2.0)  # line type[red | green]
            self.raw_linenumbers.append(vertex[6])

    def parse_line_data(self,linedata):

        # position
        pos = [linedata[0],linedata[1],linedata[2]]

        #angle
        angle = linedata[3]
        pos = rotate_pt_by_x_axis_angle(pos[0], pos[1], pos[2], angle)

        self.positions.extend(pos)
        self.max_pt = vec3_max(self.max_pt, pos)

        # for center calculating
        self.area_center_sum = vec3_add(self.area_center_sum, pos)
        self.area_center_sum_index += 1

        # get attributes of this point
        vertex = [0] * 10
        # 1 position
        vertex[0] = pos[0]
        vertex[1] = pos[1]
        vertex[2] = pos[2]

        # angle
        # angle = linedata[3]

        # 2 color
        color = [1.0,0.0,0.0] if linedata[4] == 0.0 else [0.0,1.0,0.0]
        vertex[3] = color[0]
        vertex[4] = color[1]
        vertex[5] = color[2]

        # 3 line number in gcode
        vertex[6] = linedata[5]

        # 4 type id
        vertex[7] = len(self.positions) - 1

        # 5 distance attribute
        vertex[8] = 0  # set after length is calculated

        # 6 set tool knife id
        vertex[9] = linedata[6]

        # push this vertex to container
        self.vertices.extend(vertex)
        self.vertex_types.append(1.0 if linedata[4] > 0.5 else 2.0)  # line type[red | green]
        self.raw_linenumbers.append(vertex[6])
        self.angles_of_vertices.append(angle)

    def generate_meshes(self):
        # 0 scale all points
        max_point = (max(self.max_pt[0], max(self.max_pt[1], self.max_pt[2])))

        vertex_count = len(self.positions) // 3
        vertex_float_num = 10
        self.position_scale = (2.0) if max_point == 0 else (2.0 / max_point)
        for i in range(vertex_count):
            self.vertices[vertex_float_num * i + 0] = self.positions[3 * i + 0] * self.position_scale
            self.vertices[vertex_float_num * i + 1] = self.positions[3 * i + 1] * self.position_scale
            self.vertices[vertex_float_num * i + 2] = self.positions[3 * i + 2] * self.position_scale

            # if i % 1000 == 0:
            #     print(f"{self.vertices[vertex_float_num * i + 0]} % {self.vertices[vertex_float_num * i + 1]} % {self.vertices[vertex_float_num * i + 0]}")

        # 1 calculate lengths
        self.lengths = [0] * vertex_count
        for i in range(1, vertex_count):
            pos1 = [self.vertices[vertex_float_num * (i - 1) + 0], self.vertices[vertex_float_num * (i - 1) + 1],
                    self.vertices[vertex_float_num * (i - 1) + 2]]
            pos2 = [self.vertices[vertex_float_num * (i) + 0], self.vertices[vertex_float_num * (i) + 1],
                    self.vertices[vertex_float_num * (i) + 2]]

            cur_line_len = vec3_distance(pos1, pos2)
            self.lengths[i] = self.lengths[i - 1] + cur_line_len

        # 2 set distance id
        for i in range(vertex_count):
            self.vertices[vertex_float_num * i + 8] = self.lengths[i]

        self.seg_mesh_vertex_count = 65500
        # 3 construct meshes
        self.meshes.clear()
        mesh_start_id = 0
        mesh_end_id = min(self.seg_mesh_vertex_count, vertex_count)  # not included

        while (True):
            # process each mesh
            indices = []
            for i in range(mesh_end_id - mesh_start_id):
                indices.append(i)
            # print(f"vertix index:[{mesh_start_id}-{mesh_end_id}]  indices Index:{len(indices)}")
            mesh = [self.vertices[vertex_float_num * mesh_start_id:vertex_float_num * mesh_end_id], indices]

            self.meshes.append(mesh)

            # debug
            # print("start:", mesh_start_id, self.vertices[vertex_float_num * mesh_start_id])
            # print("end:", mesh_end_id - 1, self.vertices[vertex_float_num * (mesh_end_id - 1)])

            # skip to next mesh
            if mesh_end_id == vertex_count:
                break  # run to end

            # resuse the last mesh vertex to make sure continous lines
            mesh_start_id = mesh_end_id - 1
            mesh_end_id = min(mesh_start_id + self.seg_mesh_vertex_count, vertex_count)

    def add_lines(self, rawlines):
        # parse line

        # 1 check gcode type
        is_4_axis = False
        if (len(rawlines) > 0 and 'A:' in rawlines[0]):
            is_4_axis = True

        if self.is_4_axis is None:
            self.is_4_axis = is_4_axis
        elif self.is_4_axis != is_4_axis:
            print("conflict line type!")

        # 2 parse single line
        for line in rawlines:
            self.parse_line(line.strip())

        self.generate_meshes()

    def add_data_arrs(self, rawdata,is_end=True):
        # parse line

        # 1 check gcode type
        self.is_4_axis = True

        # 2 parse single line
        for linedata in rawdata:
            self.parse_line_data(linedata)

        # get_elapsed("parse data")
        if is_end:
            self.generate_meshes()

def load_data(lines):
    #TODO:https://stackoverflow.com/questions/7111690/python-read-formatted-string

    #X: 0.0 Y: 0.0 Z: 0.0 Color: Green Tool: 1
    def map_color(color_str):
        if color_str == 'Green':
            return [0.,1.,0.]
        elif color_str == 'Red':
            return [1.,0.,0.]
        return [1.,1.,1.]


    vert_center = [0,0,0]

    meshes = []

    is_4_axis = False
    if(len(lines)>0 and 'A:' in lines[0]):
        is_4_axis = True

    print(f"is_4_axis:{is_4_axis}")

    how_many_meshes = int(len(lines) / 65500) + 1
    line_start = 0
    line_end = min(65500,len(lines))
    vertex_id = 0
    original_vertex_id = 0
    #get positions of all points
    #处理数据
    # tmp_poses = []
    # for line in lines:
    #     arr_pt = line.split(' ')

    #     #pos
    #     pos = [float(arr_pt[1]),float(arr_pt[3]),float(arr_pt[5])]
    #     tmp_poses.append(pos[0])
    #     tmp_poses.append(pos[1])
    #     tmp_poses.append(pos[2])

    #add distance position
    
    scale = 1.0
    positions = []
    max_pt = [0,0,0]
    for mesh_id in range(how_many_meshes):
        for line in lines[line_start:line_end]:
            arr_pt = line.split(' ')

            pos = [scale*float(arr_pt[1]),scale*float(arr_pt[3]),scale*float(arr_pt[5])]
            
            #angle
            if(is_4_axis):
                angle = float(arr_pt[7])

                rot_pos = rotate_pt_by_x_axis_angle(pos[0],pos[1],pos[2],angle)

                positions.append(rot_pos[0])
                positions.append(rot_pos[1])
                positions.append(rot_pos[2])
                
                max_pt[0] = max(max_pt[0],rot_pos[0])
                max_pt[1] = max(max_pt[1],rot_pos[1])
                max_pt[2] = max(max_pt[2],rot_pos[2])
            else:
                positions.append(pos[0])
                positions.append(pos[1])
                positions.append(pos[2])

                    
                max_pt[0] = max(max_pt[0],pos[0])
                max_pt[1] = max(max_pt[1],pos[1])
                max_pt[2] = max(max_pt[2],pos[2])

        line_start = line_end - 1 # -1 to process seam line between two mesh
        line_end = min(line_start+65500,len(lines))
    
    vertices_count = int(len(positions)/3)
    print(vertices_count)
    #apply scale to 2
    max_point = (max(max_pt[0],max(max_pt[1],max_pt[2])))
    scale_invert = (2.0) if max_point == 0 else (2.0 / max_point)
    for i in range(len(positions)):
        positions[i] *= scale_invert

    for i in range(vertices_count):
        vert_center[0] += positions[3*i+0]
        vert_center[1] += positions[3*i+1]
        vert_center[2] += positions[3*i+2]
    #calculate the center of target
    vert_center[0] /= vertices_count
    vert_center[1] /= vertices_count
    vert_center[2] /= vertices_count

    #calculate the distance field
    lengths = [0]*vertices_count
    for i in range(1,vertices_count):
        pos1 = [positions[3*i-3],positions[3*i-2],positions[3*i-1]]
        pos2 = [positions[3*i],positions[3*i+1],positions[3*i+2]]
        cur_line_len = len_3d(pos1,pos2)
        lengths[i] = lengths[i-1] + cur_line_len
    

    #reset
    line_start = 0
    line_end = min(65500,len(lines))
    angles_of_vertices = []
    raw_linenumbers = []
    vertex_types = []
    for mesh_id in range(how_many_meshes):

        #vertex data for each mesh
        vertices = []
        indices = []
        has_last_vertex = False
        last_vertex = []
        #start indices
        index = 0
        for line in lines[line_start:line_end]:


            arr_pt = line.split(' ')

            #pos
            pos = [scale_invert*float(arr_pt[1]),scale_invert*float(arr_pt[3]),scale_invert*float(arr_pt[5])]
            
            #angle
            if(is_4_axis):
                angle = float(arr_pt[7])

                rot_pos = rotate_pt_by_x_axis_angle(pos[0],pos[1],pos[2],angle)

                is_greenpt = arr_pt[9]=="Green"

                

                this_vertex = []
                this_vertex.append(rot_pos[0])#0
                this_vertex.append(rot_pos[1])#1
                this_vertex.append(rot_pos[2])#2  + (1.0 if is_greenpt else 0.0))

                #color
                color = map_color(arr_pt[9])
                this_vertex.append(color[0]) #3
                this_vertex.append(color[1]) #4
                this_vertex.append(color[2]) #5
                #line number
                this_vertex.append(float(arr_pt[11])) #6
                #type id
                this_vertex.append(float(vertex_id)) #7

                #distance id
                #print(f'line number:{float(arr_pt[11])}')
                raw_linenumbers.append(float(arr_pt[11]))
                this_vertex.append(lengths[original_vertex_id]) #8

                #store data in memery
                vertex_types.append(1.0 if arr_pt[9]=="Green" else 2.0) #line type[red | green]
                angles_of_vertices.append(angle)

                
                #vertex tool
                this_vertex.append(float(arr_pt[13])) #9

                # #添加重复的点（红-》绿）  不需要了
                # if(has_last_vertex):
                #     #greencolor = map_color('Green')
                #     last_vertex[0] = this_vertex[0]
                #     last_vertex[1] = this_vertex[1]
                #     last_vertex[2] = this_vertex[2]
                #     vertices += last_vertex
                #     indices.append(index)
                #     #fix
                #     index += 1
                #     vertex_id = vertex_id + 1
                #     this_vertex[7] = float(vertex_id)
                #     this_vertex[8] = float(0)
                # if(is_greenpt):
                #     has_last_vertex = True
                #     last_vertex = this_vertex.copy()
                # else:
                #     has_last_vertex = False

                
                vertices += this_vertex
            else:
                is_greenpt = arr_pt[7]=="Green"

                vertices.append(pos[0])
                vertices.append(pos[1])
                vertices.append(pos[2])

                #color
                color = map_color(arr_pt[7])
                vertices.append(color[0])
                vertices.append(color[1])
                vertices.append(color[2])
                #line number
                vertices.append(float(arr_pt[9]))
                #type id
                vertices.append(float(vertex_id))

                #distance id
                raw_linenumbers.append(float(arr_pt[9]))
                vertices.append(lengths[vertex_id])

                #store data in memery
                vertex_types.append(1.0 if arr_pt[7]=="Green" else 2.0) #line type[red | green]

                
                #vertextool
                vertices.append(float(arr_pt[11]))

            indices.append(index)
            index = index + 1
            vertex_id = vertex_id + 1
            original_vertex_id += 1

        line_start = line_end - 1 # -1 to process seam line between two mesh
        line_end = min(line_start+65500,len(lines))


        meshes.append([vertices,indices])
    print("mesh count: %d"%len(meshes))


    #meshes.append([axis_vertices,axis_indices])
    #for x in range(10):
    #    print(vertices[x])

    #lengths[vertices_count-1]: max physical distance
    return [is_4_axis,meshes,vert_center,len(lines),lengths,vertex_types,raw_linenumbers,positions,scale_invert,angles_of_vertices]



def frame_call_back_test(distance,num):
    print(f'当前line:{num}')

class GCodeViewer(Widget):
    axis = (0,0,1)
    angle = 0

    three_axis_mode = True
        
    g_old_curosr = [0,0]
    g_cursor = [0,0]
    left_button_down = False
    middle_button_down = False
    right_button_down = False
    g_wheel_data = 0
    lines_center = [0,0,0]

    display_count = 0
    total_line_count = 0
    add_dir = 1
    dynamic_display = True
    move_speed = 0.8
    move_scale = 1.0
    move_scale_by_positon = 1.0

    #清空数据
    clear_before_new_load = False

    #camera
    m_xRot = 30
    m_yRot = 180

    m_xRotTarget = 90
    m_yRotTarget = 0

    m_zoom = 1

    m_xPan = 0
    m_yPan = 0
    m_distance = 10

    m_xLookAt = 0
    m_yLookAt = 0
    m_zLookAt = 0

    m_xMin = 0
    m_xMax = 0
    m_yMin = 0
    m_yMax = 0
    m_zMin = 0
    m_zMax = 0
    m_xSize = 0
    m_ySize = 0
    m_zSize = 0

    off_x = 0
    off_y = 0

    orbit = True

    def __init__(self):
        super().__init__()
        self.canvas = RenderContext()
        if platform != 'android':
            glsl1 = 'hello_cube.glsl'
            glsl2 = 'simple.glsl'
            glsl3 = 'axis_helper.glsl'
        else:
            glsl1 = 'hello_cube_apk.glsl'
            glsl2 = 'simple_apk.glsl'
            glsl3 = 'axis_helper_apk.glsl'
        if not os.path.exists(glsl1):
            glsl1 = os.path.join(os.path.dirname(__file__), glsl1) # adjacent to code
            glsl2 = os.path.join(os.path.dirname(__file__), glsl2)
            glsl3 = os.path.join(os.path.dirname(__file__), glsl3)

        self.linemesh = RenderContext()
        self.linemesh.shader.source = glsl1

        self.pointermesh = RenderContext()
        self.pointermesh.shader.source = glsl2

        self.axisxmesh = RenderContext()
        self.axisxmesh.shader.source = glsl3
        self.axisymesh = RenderContext()
        self.axisymesh.shader.source = glsl3
        self.axiszmesh = RenderContext()
        self.axiszmesh.shader.source = glsl3


        self.meshmanager = MyMeshManager()
        #self.load('out_tap1.txt')
        # lines = []
        # with open('out.txt','r') as file:
        #     for line in file:
        #         lines.append(line)
        # self.load(lines)

        #print("pos:")
        #debug
        #self.load(lines)
        #self.set_frame_callback(frame_call_back_test)
        Clock.schedule_interval(self.increase_angle, 1/60)


    #清空渲染
    def clearDisplay(self):
        self.lengths = []
        self.vertex_types = []
        self.positions = []
        self.linemesh.clear()
        self.canvas.remove(self.linemesh)
        self.canvas.remove(self.pointermesh)
        self.pointermesh.clear()
        self.canvas.remove(self.axisxmesh)
        self.axisxmesh.clear()
        self.canvas.remove(self.axisymesh)
        self.axisymesh.clear()
        self.canvas.remove(self.axiszmesh)
        self.axiszmesh.clear()
        self.display_count = 0

    #回调逐帧
    def set_frame_callback(self, framecallback):
        self.frame_callback = framecallback

    def set_play_over_callback(self, playovercallback):
        self.play_over_callback = playovercallback

    def load_mesh_manager(self,lines):
        #清空显示
        self.clearDisplay()
        #添加对象
        self.canvas.add(self.linemesh)
        self.canvas.add(self.pointermesh)
        self.canvas.add(self.axisxmesh)
        self.canvas.add(self.axisymesh)
        self.canvas.add(self.axiszmesh)

        self.meshmanager.add_lines(lines)

        #显示mesh

        if platform != 'android':
            ff = [
                (b'my_vertex_position', 3, 'float'),
                (b'color', 3, 'float'),
                (b'type', 1, 'float'),
                (b'vertex_id', 1, 'float'),
                (b'distance_id', 1, 'float'),
                (b'vertex_tool', 1, 'float')
            ]
        else:
            ff = [
                (b'my_vertex_position', 3, 'float'),
                (b'color_att', 3, 'float'),
                (b'type', 1, 'float'),
                (b'vertex_id', 1, 'float'),
                (b'distance_id', 1, 'float'),
                (b'vertex_tool', 1, 'float')
            ]

        self.lengths = self.meshmanager.lengths
        self.vertex_types = self.meshmanager.vertex_types
        self.positions = self.meshmanager.positions
        self.raw_linenumbers = self.meshmanager.raw_linenumbers
        self.angles_of_vertices = self.meshmanager.angles_of_vertices

        self.total_line_count = self.meshmanager.get_pt_count()
        self.total_distance = self.meshmanager.lengths[-1]
        self.move_scale_by_positon = self.meshmanager.position_scale


        lines.clear()

        self.is_4_axis = self.meshmanager.is_4_axis

        obj1 = 'pointer.obj'
        obj2 = 'axis.obj'
        if not os.path.exists(obj1):
            obj1 = os.path.join(os.path.dirname(__file__), obj1)
            obj2 = os.path.join(os.path.dirname(__file__), obj2)

        self.pointer = ObjFile(obj1)
        self.axis_obj = ObjFile(obj2)


        # 旋转刀头还是线
        self.rotate_line_or_knife = False
        if (self.is_4_axis):
            self.rotate_line_or_knife = True


        with self.canvas:
            with self.linemesh:
                self.cb = Callback(self.setup_gl_context)
                for mesh in self.meshmanager.meshes:
                    Mesh(fmt=ff, vertices=mesh[0], indices=mesh[1], mode='line_strip')

                self.cb = Callback(None)

            with self.pointermesh:
                self.cb = Callback(None)
                # PushMatrix()
                m = list(self.pointer.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                # PopMatrix()
                self.cb = Callback(None)

            # axis
            with self.axisxmesh:
                self.cb = Callback(None)
                # PushMatrix()
                m = list(self.axis_obj.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                # PopMatrix()
                self.cb = Callback(None)
            with self.axisymesh:
                self.cb = Callback(None)
                # PushMatrix()
                m = list(self.axis_obj.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                # PopMatrix()
                self.cb = Callback(None)
            with self.axiszmesh:
                self.cb = Callback(None)
                # PushMatrix()
                m = list(self.axis_obj.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                # PopMatrix()
                self.cb = Callback(self.reset_gl_context)

        self.lines_center = self.meshmanager.get_center_of_view()
        self.linemesh['center_the_cube'] = Matrix().translate(-self.lines_center[0], -self.lines_center[1],
                                                              -self.lines_center[2])

        # rendering line meshes
        # self.linemesh['my_view'] = view#self.m_viewMatrix
        self.linemesh['display_count'] = -1.0
        # 0 means display all thing
        self.linemesh['vertex_type_display'] = 0.0

        # rendering pointer
        # self.pointermesh['modelview_mat'] = view#self.m_viewMatrix
        self.pointermesh['diffuse_light'] = (0.2, 0.0, 0.8)
        self.pointermesh['ambient_light'] = (0.1, 0.3, 0.1)
        self.pointermesh['offset'] = (-self.lines_center[0], -self.lines_center[1], -self.lines_center[2])

        self.update_proj()
        self.update_view()
        #force update
        self.canvas.ask_update()


    def clear_loaded_memery(self):
        if self.clear_before_new_load:
            self.clear_before_new_load = False

            self.meshmanager.clear()


    def load_array(self,tmpdataarrs,is_end=True):

        self.clear_loaded_memery()

        dataarrs = []
        # 过滤lines，插入过渡的线条数据
        last_color = -1
        last_line = -1
        for line in tmpdataarrs:

            color = line[4]

            need_regenerate = False
            if (color >= 0 and last_color >= 0):
                if (color != last_color):
                    need_regenerate = True

            if (need_regenerate):
                replace_str = last_color
                copyline = line.copy()
                copyline[4] = last_color

                dataarrs.append(copyline)
                dataarrs.append(line)

            else:
                dataarrs.append(line)

            last_line = line
            last_color = color


        if is_end:
            #清空显示
            self.clear_before_new_load = True
            self.clearDisplay()

            # get_elapsed("clear")
            #添加对象
            self.canvas.add(self.linemesh)
            self.canvas.add(self.pointermesh)
            self.canvas.add(self.axisxmesh)
            self.canvas.add(self.axisymesh)
            self.canvas.add(self.axiszmesh)


        # get_elapsed("add mesh")
        self.meshmanager.add_data_arrs(dataarrs,is_end)

        # get_elapsed("add line data")
        if is_end:
            #显示mesh
            if platform != 'android':
                ff = [
                    (b'my_vertex_position', 3, 'float'),
                    (b'color', 3, 'float'),
                    (b'type', 1, 'float'),
                    (b'vertex_id', 1, 'float'),
                    (b'distance_id', 1, 'float'),
                    (b'vertex_tool', 1, 'float')
                ]
            else:
                ff = [
                    (b'my_vertex_position', 3, 'float'),
                    (b'color_att', 3, 'float'),
                    (b'type', 1, 'float'),
                    (b'vertex_id', 1, 'float'),
                    (b'distance_id', 1, 'float'),
                    (b'vertex_tool', 1, 'float')
                ]

            self.lengths = self.meshmanager.lengths
            self.vertex_types = self.meshmanager.vertex_types
            self.positions = self.meshmanager.positions
            self.raw_linenumbers = self.meshmanager.raw_linenumbers
            self.angles_of_vertices = self.meshmanager.angles_of_vertices

            self.total_line_count = self.meshmanager.get_pt_count()
            self.total_distance = self.meshmanager.lengths[-1]
            self.move_scale_by_positon = self.meshmanager.position_scale

            self.is_4_axis = self.meshmanager.is_4_axis

            # get_elapsed("fetch meshdata")

            obj1 = 'pointer.obj'
            obj2 = 'axis.obj'
            if not os.path.exists(obj1):
                obj1 = os.path.join(os.path.dirname(__file__), obj1)
                obj2 = os.path.join(os.path.dirname(__file__), obj2)

            self.pointer = ObjFile(obj1)
            self.axis_obj = ObjFile(obj2)


            # get_elapsed("load pointer and axis mesh")
            # 旋转刀头还是线
            self.rotate_line_or_knife = False
            if (self.is_4_axis):
                self.rotate_line_or_knife = True


            with self.canvas:
                with self.linemesh:
                    self.cb = Callback(self.setup_gl_context)
                    for mesh in self.meshmanager.meshes:
                        Mesh(fmt=ff, vertices=mesh[0], indices=mesh[1], mode='line_strip')

                    self.cb = Callback(None)

                with self.pointermesh:
                    self.cb = Callback(None)
                    # PushMatrix()
                    m = list(self.pointer.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode='triangles',
                    )
                    # PopMatrix()
                    self.cb = Callback(None)

                # axis
                with self.axisxmesh:
                    self.cb = Callback(None)
                    # PushMatrix()
                    m = list(self.axis_obj.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode='triangles',
                    )
                    # PopMatrix()
                    self.cb = Callback(None)
                with self.axisymesh:
                    self.cb = Callback(None)
                    # PushMatrix()
                    m = list(self.axis_obj.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode='triangles',
                    )
                    # PopMatrix()
                    self.cb = Callback(None)
                with self.axiszmesh:
                    self.cb = Callback(None)
                    # PushMatrix()
                    m = list(self.axis_obj.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode='triangles',
                    )
                    # PopMatrix()
                    self.cb = Callback(self.reset_gl_context)

            # get_elapsed("upload mesh")

            self.lines_center = self.meshmanager.get_center_of_view()
            self.linemesh['center_the_cube'] = Matrix().translate(-self.lines_center[0], -self.lines_center[1],
                                                                  -self.lines_center[2])

            # rendering line meshes
            # self.linemesh['my_view'] = view#self.m_viewMatrix
            self.linemesh['display_count'] = -1.0
            # 0 means display all thing
            self.linemesh['vertex_type_display'] = 0.0

            # rendering pointer
            # self.pointermesh['modelview_mat'] = view#self.m_viewMatrix
            self.pointermesh['diffuse_light'] = (0.2, 0.0, 0.8)
            self.pointermesh['ambient_light'] = (0.1, 0.3, 0.1)
            self.pointermesh['offset'] = (-self.lines_center[0], -self.lines_center[1], -self.lines_center[2])

            self.update_proj()
            self.update_view()
            #force update
            self.canvas.ask_update()

            # get_elapsed("uodate frame")


    def load_1data_display(self,lines):
        #TODO:https://stackoverflow.com/questions/7111690/python-read-formatted-string

        #X: 0.0 Y: 0.0 Z: 0.0 Color: Green Tool: 1
        def map_color(color_str):
            if color_str == 'Green':
                return [0.,1.,0.]
            elif color_str == 'Red':
                return [1.,0.,0.]
            return [1.,1.,1.]


        vert_center = [0,0,0]

        meshes = []

        is_4_axis = False
        if(len(lines)>0 and 'A:' in lines[0]):
            is_4_axis = True

        print(f"is_4_axis:{is_4_axis}")

        how_many_meshes = 1#int(len(lines) / 65500) + 1
        line_start = 0
        line_end = min(65536,len(lines))
        # vertex_id = 0
        original_vertex_id = 0
        #get positions of all points
        #处理数据
        # tmp_poses = []
        # for line in lines:
        #     arr_pt = line.split(' ')

        #     #pos
        #     pos = [float(arr_pt[1]),float(arr_pt[3]),float(arr_pt[5])]
        #     tmp_poses.append(pos[0])
        #     tmp_poses.append(pos[1])
        #     tmp_poses.append(pos[2])

        #add distance position
        
        scale = 1.0
        positions = []
        max_pt = [0,0,0]
        for mesh_id in range(how_many_meshes):
            for line in lines[line_start:line_end]:
                arr_pt = line.split(' ')

                pos = [scale*float(arr_pt[1]),scale*float(arr_pt[3]),scale*float(arr_pt[5])]
                
                #angle
                if(is_4_axis):
                    angle = float(arr_pt[7])

                    rot_pos = rotate_pt_by_x_axis_angle(pos[0],pos[1],pos[2],angle)

                    positions.append(rot_pos[0])
                    positions.append(rot_pos[1])
                    positions.append(rot_pos[2])
                    
                    max_pt[0] = max(max_pt[0],rot_pos[0])
                    max_pt[1] = max(max_pt[1],rot_pos[1])
                    max_pt[2] = max(max_pt[2],rot_pos[2])
                else:
                    positions.append(pos[0])
                    positions.append(pos[1])
                    positions.append(pos[2])

                        
                    max_pt[0] = max(max_pt[0],pos[0])
                    max_pt[1] = max(max_pt[1],pos[1])
                    max_pt[2] = max(max_pt[2],pos[2])

            line_start = line_end - 1 # -1 to process seam line between two mesh
            line_end = min(line_start+65536,len(lines))
        
        vertices_count = int(len(positions)/3)
        print(vertices_count)
        #apply scale to 2
        max_point = 50.0#(max(max_pt[0],max(max_pt[1],max_pt[2])))
        scale_invert = (2.0) if max_point == 0 else (2.0 / max_point)
        for i in range(len(positions)):
            positions[i] *= scale_invert

        for i in range(vertices_count):
            vert_center[0] += positions[3*i+0]
            vert_center[1] += positions[3*i+1]
            vert_center[2] += positions[3*i+2]
        #calculate the center of target
        vert_center[0] /= vertices_count
        vert_center[1] /= vertices_count
        vert_center[2] /= vertices_count

        #calculate the distance field

        lengths = [0]*vertices_count
        for i in range(0,vertices_count):
            if i == 0:
                if len(self.positions) > 0:
                    pos1 = [self.positions[-3],self.positions[-2],self.positions[-1]]
                    pos2 = [self.positions[3*i],self.positions[3*i+1],self.positions[3*i+2]]
                    cur_line_len = len_3d(pos1, pos2)
                    lengths[i] = self.lengths[-1] + cur_line_len

            else:
                pos1 = [positions[3*i-3],positions[3*i-2],positions[3*i-1]]
                pos2 = [positions[3*i],positions[3*i+1],positions[3*i+2]]
                cur_line_len = len_3d(pos1,pos2)
                lengths[i] = lengths[i-1] + cur_line_len


        

        #reset
        line_start = 0
        line_end = min(65536,len(lines))
        angles_of_vertices = []
        raw_linenumbers = []
        vertex_types = []
        for mesh_id in range(how_many_meshes):

            #vertex data for each mesh
            vertices = []
            indices = []
            has_last_vertex = False
            last_vertex = []
            #start indices
            index = 0
            for line in lines[line_start:line_end]:


                arr_pt = line.split(' ')

                #pos
                pos = [scale_invert*float(arr_pt[1]),scale_invert*float(arr_pt[3]),scale_invert*float(arr_pt[5])]
                #pos = [float(arr_pt[1]),float(arr_pt[3]),float(arr_pt[5])]
                
                #angle
                if(is_4_axis):
                    angle = float(arr_pt[7])

                    rot_pos = rotate_pt_by_x_axis_angle(pos[0],pos[1],pos[2],angle)

                    is_greenpt = arr_pt[9]=="Green"

                    

                    this_vertex = []
                    this_vertex.append(rot_pos[0])#0
                    this_vertex.append(rot_pos[1])#1
                    this_vertex.append(rot_pos[2])#2  + (1.0 if is_greenpt else 0.0))

                    #color
                    color = map_color(arr_pt[9])
                    this_vertex.append(color[0]) #3
                    this_vertex.append(color[1]) #4
                    this_vertex.append(color[2]) #5
                    #line number
                    this_vertex.append(float(arr_pt[11])) #6
                    #type id
                    this_vertex.append(float(self.vertex_id)) #7

                    #distance id
                    #print(f'line number:{float(arr_pt[11])}')
                    raw_linenumbers.append(float(arr_pt[11]))
                    this_vertex.append(lengths[original_vertex_id]) #8

                    #store data in memery
                    vertex_types.append(1.0 if arr_pt[9]=="Green" else 2.0) #line type[red | green]
                    angles_of_vertices.append(angle)

                    
                    #vertex tool
                    this_vertex.append(float(arr_pt[13])) #9

                    # #添加重复的点（红-》绿）  不需要了
                    # if(has_last_vertex):
                    #     #greencolor = map_color('Green')
                    #     last_vertex[0] = this_vertex[0]
                    #     last_vertex[1] = this_vertex[1]
                    #     last_vertex[2] = this_vertex[2]
                    #     vertices += last_vertex
                    #     indices.append(index)
                    #     #fix
                    #     index += 1
                    #     vertex_id = vertex_id + 1
                    #     this_vertex[7] = float(vertex_id)
                    #     this_vertex[8] = float(0)
                    # if(is_greenpt):
                    #     has_last_vertex = True
                    #     last_vertex = this_vertex.copy()
                    # else:
                    #     has_last_vertex = False

                    
                    vertices += this_vertex
                else:
                    is_greenpt = arr_pt[7]=="Green"

                    vertices.append(pos[0])
                    vertices.append(pos[1])
                    vertices.append(pos[2])

                    #color
                    color = map_color(arr_pt[7])
                    vertices.append(color[0])
                    vertices.append(color[1])
                    vertices.append(color[2])
                    #line number
                    vertices.append(float(arr_pt[9]))
                    #type id
                    vertices.append(float(self.vertex_id))

                    #distance id
                    raw_linenumbers.append(float(arr_pt[9]))
                    vertices.append(lengths[original_vertex_id])

                    #store data in memery
                    vertex_types.append(1.0 if arr_pt[7]=="Green" else 2.0) #line type[red | green]

                    
                    #vertextool
                    vertices.append(float(arr_pt[11]))

                indices.append(index)
                index = index + 1
                self.vertex_id = self.vertex_id + 1
                original_vertex_id += 1

            line_start = line_end - 1 # -1 to process seam line between two mesh
            line_end = min(line_start+65500,len(lines))


            meshes.append([vertices,indices])
        print("mesh count: %d"%len(meshes))


        #meshes.append([axis_vertices,axis_indices])
        #for x in range(10):
        #    print(vertices[x])

        #lengths[vertices_count-1]: max physical distance
        return [is_4_axis,meshes,vert_center,len(lines),lengths,vertex_types,raw_linenumbers,positions,scale_invert,angles_of_vertices]


    #渐进式加载数据
    def load_with_display(self,tmplines):
        self.clearDisplay()

        #设置容器
        self.canvas.add(self.linemesh)
        self.canvas.add(self.pointermesh)
        self.canvas.add(self.axisxmesh)
        self.canvas.add(self.axisymesh)
        self.canvas.add(self.axiszmesh)

        #记录临时变量
        last_color = ''
        last_line = ''
        if platform != 'android':
            ff = [
                (b'my_vertex_position',3,'float'),
                (b'color',3,'float'),
                (b'type',1,'float'),
                (b'vertex_id',1,'float'),
                (b'distance_id',1,'float'),
                (b'vertex_tool',1,'float')
            ]
        else:
            ff = [
                (b'my_vertex_position', 3, 'float'),
                (b'color_att', 3, 'float'),
                (b'type', 1, 'float'),
                (b'vertex_id', 1, 'float'),
                (b'distance_id', 1, 'float'),
                (b'vertex_tool', 1, 'float')
            ]
        #every 65535
        meshes = []
        lines = []
        current_processed_count = 0
        self.vertex_id = 0
        for i in range(len(tmplines)):

            #process line varibles
            thisline = tmplines[i]
            color = ''
            if 'Green' in thisline:
                color = 'Green'
            elif 'Red' in thisline:
                color = 'Red'

            #process
            need_regenerate = False
            if(len(color) > 0 and len(last_color)>0):
                if(color != last_color):
                    need_regenerate = True

            # if(need_regenerate):
            #     copyline = thisline.replace(color,last_color)
                
            #     lines.append(copyline)
            #     lines.append(thisline)

            # else:
            #     lines.append(thisline)

            lines.append(thisline)

            if len(lines) == 65536:
                #create mesh and refresh display
                [is_4_axis,mmeshes,vert_center,total_line_count,lengths,vertex_types,raw_linenumbers,positions,position_scale,angles_of_vertices] = \
                    self.load_1data_display(lines)


                if len(self.positions) == 0:
                    self.lines_center = vert_center
                else:
                    total_pt_count = len(self.positions)
                    this__pt_count = len(positions)
                    total_sum_position = [ self.lines_center[0] * total_pt_count + vert_center[0] * this__pt_count,\
                                        self.lines_center[1]  * total_pt_count + vert_center[1] * this__pt_count, \
                                        self.lines_center[2]  * total_pt_count + vert_center[2] * this__pt_count]
                    
                    total_pt_count += this__pt_count
                    self.lines_center = [total_sum_position[0]/total_pt_count,total_sum_position[1]/total_pt_count,total_sum_position[2]/total_pt_count]
            

                print(vert_center)
                print(self.lines_center)
                # print(mmeshes)
                # print(lengths)
                self.lengths += lengths
                self.vertex_types += vertex_types
                self.positions += positions
                lines.clear()

                self.is_4_axis = is_4_axis
                with self.canvas:
                    with self.linemesh:
                        # self.cb = Callback(self.setup_gl_context)
                        for mesh in mmeshes:
                            Mesh(fmt=ff, vertices=mesh[0], indices=mesh[1], mode='line_strip')
                        
                        # self.cb = Callback(None)
                    
                self.linemesh['center_the_cube'] = Matrix().translate(-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])


                #rendering line meshes
                #self.linemesh['my_view'] = view#self.m_viewMatrix
                self.linemesh['display_count'] = -1.0
                #0 means display all thing
                self.linemesh['vertex_type_display'] = 0.0

                #rendering pointer
                #self.pointermesh['modelview_mat'] = view#self.m_viewMatrix
                self.pointermesh['diffuse_light'] = (0.2, 0.0, 0.8)
                self.pointermesh['ambient_light'] = (0.1, 0.3, 0.1)
                self.pointermesh['offset'] = (-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])

                self.update_proj()
                self.update_view()

        #剩下的lines
        if len(lines)>0:
            #create mesh and refresh display
            [is_4_axis,mmeshes,vert_center,total_line_count,lengths,vertex_types,raw_linenumbers,positions,position_scale,angles_of_vertices] = \
                self.load_1data_display(lines)

            
            if len(self.positions) == 0:
                self.lines_center = vert_center
            else:
                total_pt_count = len(self.positions)
                this__pt_count = len(positions)
                total_sum_position = [ self.lines_center[0] * total_pt_count + vert_center[0] * this__pt_count,\
                                      self.lines_center[1]  * total_pt_count + vert_center[1] * this__pt_count, \
                                      self.lines_center[2]  * total_pt_count + vert_center[2] * this__pt_count]
                
                total_pt_count += this__pt_count
                self.lines_center = [total_sum_position[0]/total_pt_count,total_sum_position[1]/total_pt_count,total_sum_position[2]/total_pt_count]
            
            # print(self.lines_center)
            # # print(lengths)
            # if len(lengths) > 0:
            #     last_length = 0.0
            #     if len(self.lengths)>0:
            #         last_length = self.lengths[len(self.lengths)-1] +
            #             self.positions[-1]
            #
            #     for i in range(len(lengths)):
            self.lengths += lengths

            self.vertex_types += vertex_types
            self.positions += positions
            lines.clear()

            self.is_4_axis = is_4_axis
            with self.canvas:
                
                with self.linemesh:
                    self.cb = Callback(self.setup_gl_context)
                    for mesh in mmeshes:
                        Mesh(fmt=ff, vertices=mesh[0], indices=mesh[1], mode='line_strip')
                    
                    self.cb = Callback(None)
                
            self.linemesh['center_the_cube'] = Matrix().translate(-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])


            #rendering line meshes
            #self.linemesh['my_view'] = view#self.m_viewMatrix
            self.linemesh['display_count'] = -1.0
            #0 means display all thing
            self.linemesh['vertex_type_display'] = 0.0

            #rendering pointer
            #self.pointermesh['modelview_mat'] = view#self.m_viewMatrix
            self.pointermesh['diffuse_light'] = (0.2, 0.0, 0.8)
            self.pointermesh['ambient_light'] = (0.1, 0.3, 0.1)
            self.pointermesh['offset'] = (-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])

            self.update_proj()
            self.update_view()
    #加载数据
    def load(self, tmplines):

        # self.load_mesh_manager(tmplines)
        # return

        self.clearDisplay()


        #过滤lines，插入过渡的线条数据
        lines = []
        last_color = ''
        last_line = ''
        for line in tmplines:
            color = ''
            if 'Green' in line:
                color = 'Green'
            elif 'Red' in line:
                color = 'Red'
            
            need_regenerate = False
            if(len(color) > 0 and len(last_color)>0):
                if(color != last_color):
                    need_regenerate = True
            
            if(need_regenerate):
                replace_str = last_color
                copyline = line.replace(color,last_color)
                
                lines.append(copyline)
                lines.append(line)

            else:
                lines.append(line)

            last_line = line
            last_color = color

        self.canvas.add(self.linemesh)
        self.canvas.add(self.pointermesh)
        self.canvas.add(self.axisxmesh)
        self.canvas.add(self.axisymesh)
        self.canvas.add(self.axiszmesh)
        if platform != 'android':
            ff = [
                (b'my_vertex_position',3,'float'),
                (b'color',3,'float'),
                (b'type',1,'float'),
                (b'vertex_id',1,'float'),
                (b'distance_id',1,'float'),
                (b'vertex_tool',1,'float')
            ]
        else:
            ff = [
                (b'my_vertex_position', 3, 'float'),
                (b'color_att', 3, 'float'),
                (b'type', 1, 'float'),
                (b'vertex_id', 1, 'float'),
                (b'distance_id', 1, 'float'),
                (b'vertex_tool', 1, 'float')
            ]
        
        [is_4_axis,meshes,vert_center,total_line_count,lengths,vertex_types,raw_linenumbers,positions,position_scale,angles_of_vertices] = load_data(lines)
        print("how many meshes:",len(meshes))

        self.positions = positions
        self.lengths = lengths
        self.raw_linenumbers = raw_linenumbers
        
        self.vertex_types = vertex_types
        self.move_scale_by_positon = position_scale
        self.angles_of_vertices = angles_of_vertices

        self.is_4_axis = is_4_axis
        self.total_line_count = total_line_count
        self.total_distance = lengths[len(lengths) - 1]

        obj1 = 'pointer.obj'
        obj2 = 'axis.obj'
        if not os.path.exists(obj1):
            obj1 = os.path.join(os.path.dirname(__file__), obj1)
            obj2 = os.path.join(os.path.dirname(__file__), obj2)

        self.pointer = ObjFile(obj1)

        self.axis_obj = ObjFile(obj2)

        #旋转刀头还是线
        self.rotate_line_or_knife = False
        if(self.is_4_axis):
            self.rotate_line_or_knife = True

        with self.canvas:
            
            with self.linemesh:
                self.cb = Callback(self.setup_gl_context)
                for mesh in meshes:
                    Mesh(fmt=ff, vertices=mesh[0], indices=mesh[1], mode='line_strip')
                
                self.cb = Callback(None)

            with self.pointermesh:

                self.cb = Callback(None)
                #PushMatrix()
                m = list(self.pointer.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                #PopMatrix()
                self.cb = Callback(None)
            
            #axis
            with self.axisxmesh:
                self.cb = Callback(None)
                #PushMatrix()
                m = list(self.axis_obj.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                #PopMatrix()
                self.cb = Callback(None)
            with self.axisymesh:
                self.cb = Callback(None)
                #PushMatrix()
                m = list(self.axis_obj.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                #PopMatrix()
                self.cb = Callback(None)
            with self.axiszmesh:
                self.cb = Callback(None)
                #PushMatrix()
                m = list(self.axis_obj.objects.values())[0]
                self.mesh = Mesh(
                    vertices=m.vertices,
                    indices=m.indices,
                    fmt=m.vertex_format,
                    mode='triangles',
                )
                #PopMatrix()
                self.cb = Callback(self.reset_gl_context)
        #move to center
        self.linemesh['center_the_cube'] = Matrix().translate(-vert_center[0],-vert_center[1],-vert_center[2])


        #rendering line meshes
        #self.linemesh['my_view'] = view#self.m_viewMatrix
        self.linemesh['display_count'] = -1.0
        #0 means display all thing
        self.linemesh['vertex_type_display'] = 0.0

        #rendering pointer
        #self.pointermesh['modelview_mat'] = view#self.m_viewMatrix
        self.pointermesh['diffuse_light'] = (0.2, 0.0, 0.8)
        self.pointermesh['ambient_light'] = (0.1, 0.3, 0.1)
        self.pointermesh['offset'] = (-vert_center[0],-vert_center[1],-vert_center[2])
        self.lines_center = vert_center

        self.update_proj()
        self.update_view()
        #print(self.size)
        #init for arccamera

    def update_proj(self):
        asp = self.size[0] / self.size[1] 
        proj = Matrix()
        zoomidx = self.m_zoom
        #proj.perspective(45,aspect,.1,100)
        proj.view_clip((-0.5 + self.m_xPan) * asp * zoomidx, (0.5 + self.m_xPan) * asp * zoomidx, (-0.5 + self.m_yPan)*zoomidx, (0.5 + self.m_yPan)*zoomidx, 2, self.m_distance * 2,1)
        self.linemesh['my_proj'] = proj
        self.pointermesh['projection_mat'] = proj
        self.axisxmesh['projection_mat'] = proj
        self.axisymesh['projection_mat'] = proj
        self.axiszmesh['projection_mat'] = proj

    def update_view(self):
        #self.m_viewMatrix = Matrix()
        r = self.m_distance
        angY = -M_PI / 180.0 * self.m_yRot
        angX = M_PI / 180.0 * self.m_xRot

        eye = (r * math.cos(angX) * math.sin(angY) + self.m_xLookAt, r * math.cos(angX) * math.cos(angY) + self.m_yLookAt, r * math.sin(angX) + self.m_zLookAt)
        
        center = (self.m_xLookAt, self.m_yLookAt, self.m_zLookAt)
        up = (-math.sin(angY + (M_PI if self.m_xRot < 0 else 0)) if abs(self.m_xRot) == 90 else 0, 
            -math.cos(angY + (M_PI if self.m_xRot < 0 else 0)) if abs(self.m_xRot) == 90 else 0,
            math.cos(angX))
        up = normalize(up)
        self.m_viewMatrix=Matrix().look_at(eye[0],eye[1],eye[2], center[0],center[1],center[2],up[0],up[1],up[2])

        #self.m_viewMatrix = self.m_viewMatrix.translate(self.m_xLookAt, self.m_yLookAt, self.m_zLookAt)
        #self.m_viewMatrix = self.m_viewMatrix.scale(self.m_zoom, self.m_zoom, self.m_zoom)
        #self.m_viewMatrix = self.m_viewMatrix.translate(-self.m_xLookAt, -self.m_yLookAt, -self.m_zLookAt)
        #self.m_viewMatrix = self.m_viewMatrix.rotate(-90, 1.0, 0.0, 0.0)

    def setup_gl_context(self, *args):
        glViewport(self.pos[0]+self.off_x,self.pos[1]+self.off_y,self.size[0],self.size[1])
        glEnable(GL_DEPTH_TEST)
        #glDisable(GL_CULL_FACE)
        pass
    def reset_gl_context(self, *args):
        glDisable(GL_DEPTH_TEST)
        #glEnable(GL_CULL_FACE)
        glViewport(0,0,Window.size[0],Window.size[1])
        pass

    #get total segment count
    def get_total_seg_count(self):
        return self.total_line_count

    #get max distance
    def get_total_distance(self):
        return self.lengths[len(self.lengths)-1]

    #set display offset
    def set_display_offset(self,offx,offy):
        self.off_x = offx
        self.off_y = offy

    #set displaying limit
    def set_pos_by_distance(self,distance):
        if distance > self.get_total_distance():
            print("distance is out of bounds")
            return
        self.display_count = float(distance)

    #根据line number 返回实际距离
    #TODO:need test
    def get_distance_by_lineidx(self,lineidx,ratio):
        left_pos = binary_find_left(self.raw_linenumbers,lineidx)
        while(left_pos>0 and self.raw_linenumbers[left_pos-1] == lineidx):
            left_pos = left_pos - 1

        right_pos = left_pos
        while (right_pos<len(self.raw_linenumbers)-1 and self.raw_linenumbers[right_pos+1] == lineidx):
            right_pos = right_pos + 1
        #skip to next pos(lineidx+1)
        right_pos = right_pos + 1
        #start point
        start_distance = self.lengths[left_pos]
        end_distance = self.lengths[right_pos]

        return start_distance*(1.0 - ratio) + end_distance * ratio

    #根据line number 返回实际距离
    def set_distance_by_lineidx(self,lineidx,ratio):
        left_pos = binary_find_left(self.raw_linenumbers,lineidx)
        while(left_pos>0 and self.raw_linenumbers[left_pos-1] == lineidx):
            left_pos = left_pos - 1

        right_pos = left_pos
        while(right_pos<len(self.raw_linenumbers)-1 and self.raw_linenumbers[right_pos+1] == lineidx):
            right_pos = right_pos + 1
        #skip to next pos(lineidx+1)
        right_pos = right_pos + 1
        #start point
        start_distance = self.lengths[left_pos]
        end_distance = self.lengths[right_pos]

        cur_distance = start_distance*(1.0 - ratio) + end_distance*ratio
        self.set_pos_by_distance(cur_distance)

    #获得当前显示位置和行号
    def get_cur_pos_index(self):
        line_number = -1
        
        #print(f'cur_line_index:{self.cur_line_index},raw_linenumbers size:{len(self.raw_linenumbers)}')
        if self.cur_line_index < len(self.raw_linenumbers):
            line_number = self.raw_linenumbers[int(self.cur_line_index)]
        
        return [self.display_count,line_number]

    #设置自动走刀路
    def enable_dynamic_displaying(self,dynamic_display):
        self.dynamic_display = dynamic_display

    #显示全部数据
    def show_all(self):
        self.dynamic_display = False
        self.display_count = self.get_total_distance()

    #恢复默认视角
    def restore_default_view(self):
        self.m_xLookAt = 0
        self.m_yLookAt = 0
        self.m_zLookAt = 0
        self.m_xRot = 30
        self.m_yRot = 180
        self.m_zoom = 1
        self.m_xPan = 0
        self.m_yPan = 0
        self.update_proj()
        self.update_view()

    #设置移动速度
    def set_move_speed(self,mov_speed):
        self.move_speed = mov_speed

    #设置显示mask(float)最多支持5种类别
    #1：显示第一类
    #10:显示第二类
    #11：显示第一类和第二类
    def set_display_mask(self,mask_val):
        #if(mask_val > 999999):
        #    mask_val -= int(mask_val / 1000000) * 1000000
        self.linemesh['vertex_type_display'] = mask_val

    #repeat this function every 1/60 s
    def increase_angle(self,_):

        if(not hasattr(self,'lengths') or self.lengths is None or len(self.lengths)<=1):
            #data is not loaded yet
            return
        
        #calculate the current distance of line segment
        #print(self.pos)
        #print(self.size)
        self.update_proj()
        if self.dynamic_display:
            self.add_dir = self.move_speed * self.move_scale * self.move_scale_by_positon

            if (self.display_count >= self.get_total_distance()):
                self.dynamic_display = False
            else:
                self.display_count = self.display_count + self.add_dir

            

        #debug
        #self.display_count = self.get_total_distance()

        

        self.linemesh['display_count'] = float(self.display_count)

        #which segment we are located
        cur_display_distance = float(self.display_count)
        line_index = binary_find_left(self.lengths,cur_display_distance)
        line_ratio = 0
        if(line_index < len(self.lengths)-1):
            line_ratio = (cur_display_distance - self.lengths[int(line_index)]) / \
                (self.lengths[int(line_index)+1]- self.lengths[int(line_index)])
            
        line_index_withratio = line_index + line_ratio

        self.cur_line_index = line_index_withratio

        #逐帧回调
        if(hasattr(self,'frame_callback') and self.frame_callback is not None):
            [cur_distance,linenumber]= self.get_cur_pos_index()
            self.frame_callback(cur_distance,linenumber)
            #debug
            # if(linenumber>100):
            #     lines = []
            #     with open('out2.txt','r') as file:
            #         for line in file:
            #             lines.append(line)
            #     self.load(lines)
            #     return

        #print(self.vertex_types[line_index])
        if(self.vertex_types[line_index] > 1.0):
            self.move_scale = 2.0
        else:
            self.move_scale = 1.0



        #print(view)
        self.linemesh['my_rotation'] = Matrix() #rotation_mat#
        
        self.linemesh['my_view'] = self.m_viewMatrix#rotation_mat
           
        pointer_updated_pos = 3*int(line_index_withratio)
        #print(pointer_updated_pos)
        
        #if(not self.is_4_axis):
        self.pointermesh['rotation'] = Matrix()#rotate_mat_by_x_axis_angle(0)
        #.rotate(-90, 1.0, 0.0, 0.0)
        if pointer_updated_pos < len(self.positions):
            base_start = int(line_index_withratio)
            ratio = line_index_withratio - base_start
            offset = 0.0
            # print(f"{pointer_updated_pos} / {len(self.positions)}\n")

            #load func
            #last_pos = [self.positions[pointer_updated_pos]-self.lines_center[0],self.positions[pointer_updated_pos+1]-self.lines_center[1],self.positions[pointer_updated_pos+2]-self.lines_center[2]]
            #load_meshmanager func
            last_pos = vec3_sub(self.meshmanager.get_vertex_position(int(line_index_withratio)),self.lines_center)

            if(self.is_4_axis):
                last_angle = self.angles_of_vertices[int(pointer_updated_pos/3)]
            
            if(ratio>0.0 and pointer_updated_pos+5 < len(self.positions)):
                #next_pos = [self.positions[pointer_updated_pos+3]-self.lines_center[0],self.positions[pointer_updated_pos+4]-self.lines_center[1],self.positions[pointer_updated_pos+5]-self.lines_center[2]]
                # load_meshmanager func
                next_pos = vec3_sub(self.meshmanager.get_vertex_position(int(line_index_withratio)+1),self.lines_center)
                lerp_pos = [next_pos[0] * ratio + (1.0 - ratio)*last_pos[0],next_pos[1] * ratio + (1.0 - ratio)*last_pos[1],next_pos[2] * ratio + (1.0 - ratio)*last_pos[2]]
                self.pointermesh['offset'] = lerp_pos
                
                #print(f'{lerp_pos[0]+self.lines_center[0]}')
                #normal    
                #calculate normal of pointer
                if(self.is_4_axis):
                    next_angle = self.angles_of_vertices[int(pointer_updated_pos/3)+1]
                    lerp_angle = next_angle * ratio + (1.0 - ratio)*last_angle
                    # lerp_angle = 0 - lerp_angle
                    if(not self.rotate_line_or_knife):
                        self.pointermesh['rotation'] = rotate_mat_by_x_axis_angle(lerp_angle)
                    else:
                        #self.linemesh['my_view']=self.linemesh['my_view'].multiply(rotate_mat_by_x_axis_angle(-lerp_angle))
                        self.linemesh['my_rotation'] = rotate_mat_by_x_axis_angle(-lerp_angle)
                        len_to_center = len_2d([lerp_pos[1],lerp_pos[2]],[-self.lines_center[1],-self.lines_center[2]])
                        #print(f'{len_to_center}')
                        rot_point = self.linemesh['my_rotation'].transform_point(lerp_pos[0],lerp_pos[1],lerp_pos[2])


                        self.pointermesh['offset'] = rot_point#[x_offset-self.lines_center[0],y_offset-self.lines_center[1], z_offset-self.lines_center[2]]
            else:
                #wont enter here
                #self.pointermesh['offset'] = last_pos
                if(self.is_4_axis):
                    if(not self.rotate_line_or_knife):
                        self.pointermesh['rotation'] = rotate_mat_by_x_axis_angle(last_angle)
                    else:
                        self.linemesh['my_view']=self.linemesh['my_view'].multiply(rotate_mat_by_x_axis_angle(-last_angle))
                        
                        len_to_center = len_3d(last_pos,[-self.lines_center[0],-self.lines_center[1],0])
                        self.pointermesh['offset'] = [-self.lines_center[0],-self.lines_center[1],len_to_center -self.lines_center[2]]


        
        
        self.pointermesh['modelview_mat'] = Matrix().multiply(self.m_viewMatrix)

        #axis
        self.axisxmesh['offset'] = (-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])
        self.axisxmesh['rotation'] = Matrix()
        self.axisxmesh['diff_color'] = [0.0,1.0,0.0] 
        #self.axisxmesh['rotation'] = self.axisxmesh['rotation'].rotate(0.5*3.1415926,0,1,0)

        self.axisymesh['offset'] = (-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])
        self.axisymesh['rotation'] = Matrix()
        self.axisymesh['rotation'] = self.axisymesh['rotation'].rotate(0.5*3.1415926,1,0,0)
        self.axisymesh['diff_color'] = [0.0,0.0,1.0]
        
        
        self.axiszmesh['offset'] = (-self.lines_center[0],-self.lines_center[1],-self.lines_center[2])
        self.axiszmesh['rotation'] = Matrix()
        self.axiszmesh['rotation'] = self.axiszmesh['rotation'].rotate(-0.5*3.1415926,0,0,1)
        self.axiszmesh['diff_color'] = [1.0,0.0,0.0] 

        
        self.axisxmesh['modelview_mat'] = self.m_viewMatrix#rotation_mat
        self.axisymesh['modelview_mat'] = self.m_viewMatrix#rotation_mat
        self.axiszmesh['modelview_mat'] = self.m_viewMatrix#rotation_mat

        self.g_old_curosr  = self.g_cursor
        self.g_wheel_data = 0

    #mouse event
    #     return super(GCodeViewer, self).on_touch_move(touch)
    #     if self.collide_point(*touch.pos):
    #
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            try:
                touchpos = [touch.pos[0], self.size[1] - touch.pos[1]]
                self.m_lastPos = touchpos.copy()
                self.m_xLastRot = self.m_xRot
                self.m_yLastRot = self.m_yRot
                self.m_xLastPan = self.m_xPan
                self.m_yLastPan = self.m_yPan

                if 'button' in touch.profile:
                    if touch.is_mouse_scrolling:
                        if touch.button == 'scrolldown':
                            self.zoom_out()
                        elif touch.button == 'scrollup':
                            self.zoom_in()

                self.update_proj()
                self.update_view()

                if touch.is_double_tap:
                    self.restore_default_view()

            except:
                print(sys.exc_info()[1])

    def on_touch_move(self, touch):
        if self.collide_point(*touch.pos):
            try:
                touchpos = [touch.pos[0], self.size[1] - touch.pos[1]]

                if (not 'button' in touch.profile or touch.button == 'left'):
                    if self.orbit:
                        self.m_yRot = normalize_angle(self.m_yLastRot - (touchpos[0] - self.m_lastPos[0]) * 0.5)
                        self.m_xRot = self.m_xLastRot + (touchpos[1] - self.m_lastPos[1]) * 0.5

                        if (self.m_xRot < -90): self.m_xRot = -90.0
                        if (self.m_xRot > 90): self.m_xRot = 90.0

                        self.update_view()
                    else:
                        self.m_xPan = self.m_xLastPan - (touchpos[0] - self.m_lastPos[0]) * 1 / self.size[0]
                        self.m_yPan = self.m_yLastPan + (touchpos[1] - self.m_lastPos[1]) * 1 / self.size[1]

                        self.update_proj()

                elif ('button' in touch.profile and touch.button == 'right'):
                    self.m_xPan = self.m_xLastPan - (touchpos[0] - self.m_lastPos[0]) * 1 / self.size[0]
                    self.m_yPan = self.m_yLastPan + (touchpos[1] - self.m_lastPos[1]) * 1 / self.size[1]

                    self.update_proj()

                self.g_cursor = [touch.pos[0], touch.pos[1]]
            except:
                print(sys.exc_info()[1])

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            try:
                self.g_old_curosr = self.g_cursor = [touch.pos[0], touch.pos[1]]
            except:
                print(sys.exc_info()[1])

    def zoom_in(self):
        if (self.m_zoom > 0.1):
            self.m_zoom /= ZOOMSTEP
            self.update_proj()
            self.update_view()

    def zoom_out(self):
        if (self.m_zoom < 10):
            self.m_zoom *= ZOOMSTEP
            self.update_proj()
            self.update_view()

    def set_orbit(self, orbit = True):
        self.orbit = orbit


#----------------test func----------------------

if __name__ == '__main__':
    import re
    class MyApp(App):
        def build(self):
            viewer = GCodeViewer()
            viewer.set_play_over_callback(frame_call_back_test)
            filename = 'parsernew/out_tap2.txt'
            lines = []
            # with open(filename,'r') as file:
            #     for line in file:
            #         if(len(line.strip()) > 0):
            #             lines.append(line)

            # filename = 'parsernew/laser test.txt'
            # lines = []
            # with open(filename,'r') as file:
            #     for line in file:
            #         line = line.strip()
            #         if(len(line) > 0):
            #             line = line[1:-1] #remove ( and )
            #             segs = line.split(',')
            #             segs = [x.replace(',','').strip()  for x in segs]
                        
            #             color_str = 'Red' if segs[4] == 'True' else 'Green'
            #             newline = f'X: {segs[0]} Y: {segs[1]} Z: {segs[2]} A: {segs[3]} Color: {color_str} Line: {segs[5]} Tool: 1'
            #             lines.append(newline)



            # viewer.load(lines)
            # viewer.load_with_display(lines)
            # viewer.show_all()

            # with open("parsernew/out_tap2.txt") as file:
            #     lines = []
            #     for line in file:
            #         lines.append(line)
            # seg = 60000
            # for i in range(len(lines) // seg + 1):
            #     end = min((1 + i) * seg, len(lines))
            #     print(f"{i * seg} -> {end}")
            #     viewer.load_mesh_manager(lines[(i * seg):(i * seg + seg)])

            # with open('parsernew/gcodes.txt',"r") as file:
            #     content = file.read()[1:-2]
            #     arraylines = content.split('\', \'')
            #     for line in arraylines:
            #         lines.append(line.replace("\'","").strip())

            data_arr = []
            with open('parsernew/gcodes(1).txt',"r") as file:
            # with open('parsernew/laser.txt', "r") as file:
                content = file.read()[2:-2]
                arraylines = content.split('], [')
                for line in arraylines:
                    arr = line.split(',')
                    linedata = [float(arr[0]),float(arr[1]),float(arr[2]),float(arr[3]),float(arr[4]),float(arr[5]),float(arr[6])]
                    lines.append(linedata)

            # with open('parsernew/laser_old.txt', "r") as file:
            #     content = file.read()[2:-2]
            #     arraylines = content.split('\', \'')
            #
            # viewer.load(arraylines)
            # viewer.show_all()
            # return viewer
            # with open('parsernew/laser_old.txt', "r") as file:
            #     content = file.read()[2:-2]
            #     arraylines = content.split('\', \'')
            #     for line in arraylines:
            #         arr = re.split(":|\s",line)[2::3]
            #         linedata = [float(arr[0]),float(arr[1]),float(arr[2]),float(arr[3]),0.0 if arr[4] == "Red" else 1.0,float(arr[5]),float(arr[6])]
            #         lines.append(linedata)


            # viewer.load(lines)
            get_elapsed("start")

            #1.169662
            # get_elapsed("start_once")
            # viewer.load_array(lines)
            # get_elapsed("loaded")

            #4.619259
            get_elapsed("start_multiple")
            step = 10000
            for idx in range(1):
                for i in range(len(lines)//step+1):
                    start_idx = i * step
                    end_idx = min((i+1)*step,len(lines))
                    is_end = end_idx == len(lines)
                    # print(f"{start_idx}-{end_idx} {is_end}")
                    viewer.load_array(lines[start_idx:end_idx],is_end)
                get_elapsed(f"loaded {idx}")

                viewer.set_distance_by_lineidx(1000,0.5)



            # viewer.enable_dynamic_displaying(True)
            viewer.show_all()
            return viewer

    #load_data('data/raw_pts.txt')
    MyApp().run()
